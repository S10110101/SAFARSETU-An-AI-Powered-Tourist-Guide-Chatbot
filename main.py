import json
import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.error import BadRequest
from deep_translator import GoogleTranslator
import os
import asyncio

# Load Havelis from JSON


LANGUAGES = {
    "en": {"name": "English", "keywords": ["english", "eng", "en", "angrezi"]},
    "hi": {"name": "हिन्दी", "keywords": ["hindi", "hin", "hi", "हिंदी"]},
    "ur": {"name": "اردو", "keywords": ["urdu", "ur", "اردو"]}
}

# Constants
MAX_CAPTION_LENGTH = 1000
MAX_MESSAGE_LENGTH = 4000

# Translation function
async def translate(text, target_lang):
    if target_lang == "en" or not text.strip():
        return text
    try:
        return GoogleTranslator(source="auto", target=target_lang).translate(text)
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return text

# TTS generation with edge-tts

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_language_menu(update, context)

async def send_language_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("English", callback_data="lang_en"),
            InlineKeyboardButton("हिन्दी", callback_data="lang_hi"),
            InlineKeyboardButton("اردو", callback_data="lang_ur")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text("Please select your language:", reply_markup=reply_markup)
    else:
        await update.callback_query.message.reply_text("Please select your language:", reply_markup=reply_markup)

# Handle greetings
async def handle_greeting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    greetings = ["hello", "hey", "hola", "namaste", "salam", "start", "begin"]
    text = update.message.text.lower()

    if any(greet in text for greet in greetings):
        # Greet back in user's language if available
        lang = context.user_data.get("lang", "en")
        greeting_response = await translate("Hello! Welcome to Haveli Guide.", lang)
        await update.message.reply_text(greeting_response)
        await send_language_menu(update, context)
        return True
    return False

# Language selection
async def language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang_code = query.data.split("_")[1]
    context.user_data["lang"] = lang_code

    # Translate all haveli names asynchronously
    translate_tasks = []
    for haveli in HAVELIS:
        translate_tasks.append(translate(haveli["name"], lang_code))

    translated_list = await asyncio.gather(*translate_tasks)
    context.user_data["results"] = translated_list
    context.user_data["search_index"] = 0

    await show_havelis_menu(query, context)

async def show_havelis_menu(query, context):
    current_index = context.user_data["search_index"]
    translated_list = context.user_data["results"]

    keyboard = []
    for i, name in enumerate(translated_list[current_index:current_index+5], start=current_index):
        keyboard.append([InlineKeyboardButton(name, callback_data=f"haveli_{i}")])

    nav_buttons = []
    if nav_buttons:
        keyboard.append(nav_buttons)

    try:
        await query.edit_message_text(
            text="Choose a haveli to explore:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Menu not modified, ignoring edit request")
        else:
            logger.error(f"Error showing menu: {e}")
            await query.message.reply_text("Please select a haveli:")

# Paginate next/prev
async def paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    direction = query.data

    current_index = context.user_data["search_index"]
    if direction == "next":
        context.user_data["search_index"] = current_index + 5
    elif direction == "prev":
        context.user_data["search_index"] = current_index - 5

    await show_havelis_menu(query, context)

# Haveli detail handler
async def send_haveli_content(index, context, chat_id, lang):
    haveli = HAVELIS[index]

    # Store current haveli for possible language change
    context.user_data["current_haveli"] = index

    # Notify user that content is being generated
    generating_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=await translate("🔍 Preparing your content...", lang)
    )

    # Translate content asynchronously


    translated_name, translated_desc, location_prefix = await asyncio.gather(
        name_task, desc_task, location_task
    )

    # Send image with name only as caption
    try:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=haveli["image"],
            caption=f"*{escaped_name}*",
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"*{escaped_name}*",
            parse_mode="MarkdownV2"
        )

    # Send description in properly sized chunks
    if translated_desc:
        escaped_desc = clean_text(translated_desc)
        desc_chunks = []
        current_chunk = ""

        # Split by sentences to preserve readability
        sentences = escaped_desc.split('. ')
        for sentence in sentences:
            if len(current_chunk) + len(sentence) + 2 < MAX_MESSAGE_LENGTH:
                current_chunk += sentence + '. '
            else:
                desc_chunks.append(current_chunk.strip())
                current_chunk = sentence + '. '

        if current_chunk:
            desc_chunks.append(current_chunk.strip())

        # Send the description chunks
        for chunk in desc_chunks:
            await context.bot.send_message(chat_id=chat_id, text=chunk)

    # Send location as clickable link
    if haveli.get("location_link"):
        location_text = f"{location_prefix}{haveli['location_link']}"
    else:
        location_text = f"{location_prefix}{haveli['location']}"

    await context.bot.send_message(
        chat_id=chat_id,
        text=clean_text(location_text),
        parse_mode="MarkdownV2"
    )

        # Feedback
    feedback_text = await translate("Was this information helpful?", lang)
    feedback_keyboard = [
        [
            InlineKeyboardButton("👍", callback_data=f"feedback_{index}_up"),
            InlineKeyboardButton("👎", callback_data=f"feedback_{index}_down")
        ]
    ]
    await context.bot.send_message(
        chat_id=chat_id,
        text=feedback_text,
        reply_markup=InlineKeyboardMarkup(feedback_keyboard)
    )

    # Delete the initial generating message
    await generating_msg.delete()

# Feedback handler with follow-up
async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        parts = query.data.split('_')
        index = int(parts[1])
        sentiment = parts[2]
        user_id = query.from_user.id

        logger.info(f"Feedback from user {user_id} for haveli {index}: {sentiment}")

        if sentiment == "up":
            response = await translate("Thank you for your feedback!", context.user_data["lang"])
        else:
            response = await translate("Thanks! We'll improve it.", context.user_data["lang"])

        try:
            await query.edit_message_text(esponse)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.info("Feedback response not modified, ignoring")
            else:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=response
                )

        # Ask if user needs more help
        followup_text = await translate(Do you need information about another haveli?", context.user_data["lang"])
        followup_keyboard = [
            [
                InlineKeyboardButton("✅ Yes", callback_data="more_help_yes"),
                InlineKeyboardButton("❌ No", callback_data="more_help_no")
            ]
        ]
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=followup_text,
            reply_markup=InlineKeyboardMarkup(followup_keyboard))
    except Exception as e:
        logger.error(f"Feedback error: {e}")
        try:
            await query.edit_message_tex("⚠️ Feedback processing failed")
        except BadRequest:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="⚠️ Feedback processing failed"
            )

# Handle follow-up after feedback
async def handle_more_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "more_help_yes":
        await query.edit_message_text(await translate("Great! Here's the haveli list:", context.user_data["lang"]))
        await show_havelis_menu(query, context)
    else:
        farewell = await translate("Thak you for using our bot! Type /start anytime to begin again.", context.user_data["lang"])
        await query.edit_message_text(farewell)

# Handle language change requests
async def handle_language_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    lang_code = None

    # Find requested language
    for code, lang_data in LANGUAGES.items():
        if any(keyword in text for keyord in lang_data["keywords"]):
            lang_code = code
            break

    if lang_code:
        context.user_data["lang"] = lang_code
        lang_name = LANGUAGES[lang_code]["name"]
        response_msg = await translate(f"Language set to {lang_name}.", context.user_data["lang"])

        # Check if we have a current haveli to regenerate
        if "current_haveli" in context.user_data:
            index = context.user_data["current_haveli"]
            await update.message.reply_text(response_msg)
            # Regenerate the current haveli in the new language
            await send_haveli_content(index, context, update.message.chat_id, lang_code)
        else:
            await update.message.reply_text(response_msg)
            await send_language_meu(update, context)
    else:
        await unknown(update, context)

# Callback dispatcher
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        data = query.data

        if data.startswith("lang_"):
            await language_selection(update, context)
        elif data in ["next", "prev"]:
            await paginate(update, context)
        elif data.startswith("haveli_"):
            await haveli_detail(update, context)
        elif data.startswith("feedback_"):
            await handle_feedback(update, context)
        elif data.startswith("more_help_"):
            await handle_more_help(update, context)
    except Exception as e:
        logger.error(f"Callback handler error: {e}")
        try:
            await update.callback_query.message.reply_text("⚠️ An error occurred. Please try again.")
        except:
            pass

# Handle text messages
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # First check for greetings
    if await handle_greeting(update, context):
        return

    # Then check for language change requests
    user_text = update.message.text.lower()
    for lang_data in LANGUAGES.values():
        if any(keyword in user_text for keyword in lang_data["keywords"]):
            await handle_language_change(update, context)
            return

    # Otherwise show unknown command
    await unknown(update, context)

# Unknown command
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", "en")
    text = await translate("Please use the buttons or type /start to begin.", lang)
    await update.message.reply_text(text)

# Error handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception while handling update: {context.error}", exc_info=True)

    if update and hasattr(update, 'message') and update.message:
        lang = context.user_data.get("lang", "en")
        text = await translate("⚠️ An unexpected error occurred. Please try again.", lang)
        await update.message.reply_text(text)

# Main
if __name__ == "__main__":
    TOKEN = ("BOT_TOKEN")
    if not TOKEN:
        logger.error("BOT_TOKEN environment variable not set!")
        exit(1)

    app = Application.builder().token(TOKEN).build()

    # Register error handler
    app.add_error_handler(error_handler)

    logger.info("Bot is running...")
    app.run_polling()
