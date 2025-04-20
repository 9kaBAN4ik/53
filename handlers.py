from aiogram import Router, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram import F
from database.db import Database
import config

router = Router()

class UserStates(StatesGroup):
    WAITING_FOR_SERVER = State()
    WAITING_FOR_TEXT = State()
    WAITING_FOR_PHOTO = State()
    CONFIRM_PHOTO_OPTION = State()


def get_main_menu(user_id: int) -> ReplyKeyboardMarkup:
    base_buttons = [[KeyboardButton(text="📝 Создать объявление")]]

    # Проверяем, является ли пользователь администратором
    if Database.is_admin(user_id) or user_id in config.ADMIN_IDS:
        base_buttons.append([KeyboardButton(text="🛠 Админ-панель")])

    return ReplyKeyboardMarkup(
        keyboard=base_buttons,
        resize_keyboard=True
    )

@router.message(Command("start"))
async def start(message: Message, state: FSMContext):
    db = Database()
    db.add_user_if_not_exists(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name
    )
    db.close()

    await state.clear()
    await message.answer(
        "👋 Добро пожаловать в *BLACK russia Б/У РЫНОК*\n\n"
        "🛍️ *SellVibe* — бот для быстрой подачи объявлений!\n\n"
        "✍️ Подавай объявление, лови хороший вайб! Нажми кнопку ниже ⬇️",
        reply_markup=get_main_menu(message.from_user.id),
        parse_mode="Markdown"
    )

@router.message(F.text == "📝 Создать объявление")
async def create_advertisement_entry(message: Message, state: FSMContext):
    await message.answer(
        "Выберите сервер для размещения объявления:",
        reply_markup=await get_servers_keyboard()
    )
    await state.set_state(UserStates.WAITING_FOR_SERVER)

async def get_servers_keyboard(page=0):
    db = Database()
    servers = db.get_servers()
    db.close()

    # Параметры пагинации
    servers_per_page = 5
    start = page * servers_per_page
    end = start + servers_per_page
    paged_servers = servers[start:end]

    # Кнопки для серверов
    buttons = [
        [InlineKeyboardButton(text=name, callback_data=f"server_{server_id}")]
        for server_id, name in paged_servers
    ]

    # Кнопки для переключения страниц
    pagination_buttons = []
    if page > 0:
        pagination_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"page_{page - 1}"))
    if end < len(servers):
        pagination_buttons.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"page_{page + 1}"))

    # Добавление кнопок пагинации
    if pagination_buttons:
        buttons.append(pagination_buttons)

    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.callback_query(F.data.startswith("server_"))
async def process_server_selection(callback: CallbackQuery, state: FSMContext):
    server_id = int(callback.data.split("_")[1])
    await state.update_data(server_id=server_id)
    await callback.message.answer(
        "✍️ Отправьте текст объявления (и только *одно* фото после этого).\n\nЕсли хотите отменить — нажмите кнопку ниже.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отменить", callback_data="cancel")
        ]]),
        parse_mode="Markdown"
    )
    await state.set_state(UserStates.WAITING_FOR_TEXT)

@router.message(UserStates.WAITING_FOR_TEXT)
async def process_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer(
        "Хотите ли вы добавить фото к объявлению?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📸 Добавить фото", callback_data="add_photo")],
            [InlineKeyboardButton(text="🚀 Отправить без фото", callback_data="no_photo")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel")]
        ])
    )
    await state.set_state(UserStates.CONFIRM_PHOTO_OPTION)

@router.callback_query(F.data == "add_photo")
async def handle_add_photo(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📸 Отправьте *фото* для объявления", parse_mode="Markdown")
    await state.set_state(UserStates.WAITING_FOR_PHOTO)

@router.message(UserStates.WAITING_FOR_PHOTO, F.photo)
async def process_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    if 'text' not in data or 'server_id' not in data:
        await message.answer("❗ Что-то пошло не так. Начните заново командой /start.")
        await state.clear()
        return

    photo_id = message.photo[-1].file_id

    db = Database()
    try:
        ad_id = db.add_advertisement(
            user_id=message.from_user.id,
            server_id=data['server_id'],
            text=data['text'],
            photo_id=photo_id
        )

        server = db.get_server(data['server_id'])
        moderation_group_id = server[3]

        await message.bot.send_photo(
            chat_id=moderation_group_id,
            photo=photo_id,
            caption=f"Новое объявление #{ad_id}\n\n{data['text']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{ad_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{ad_id}")
            ]])
        )

        await message.answer("✅ Ваше объявление отправлено на модерацию!", reply_markup=get_main_menu(message.from_user.id))
    finally:
        db.close()
        await state.clear()

@router.callback_query(F.data.startswith("page_"))
async def handle_page_navigation(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])
    await callback.message.edit_text(
        "Выберите сервер для размещения объявления:",
        reply_markup=await get_servers_keyboard(page)
    )


@router.callback_query(F.data == "no_photo")
async def handle_no_photo(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if 'text' not in data or 'server_id' not in data:
        await callback.message.answer("❗ Что-то пошло не так. Начните заново командой /start.")
        await state.clear()
        return

    db = Database()
    try:
        ad_id = db.add_advertisement(
            user_id=callback.from_user.id,
            server_id=data['server_id'],
            text=data['text'],
            photo_id=None  # <- Без фото
        )

        server = db.get_server(data['server_id'])
        moderation_group_id = server[3]

        await callback.bot.send_message(
            chat_id=moderation_group_id,
            text=f"Новое объявление #{ad_id}\n\n{data['text']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{ad_id}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{ad_id}")
                ]
            ])
        )

        await callback.message.answer("✅ Ваше объявление отправлено на модерацию!", reply_markup=get_main_menu(callback.from_user.id))
    finally:
        db.close()
        await state.clear()


@router.callback_query(F.data == "cancel")
async def cancel_advertisement(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание объявления отменено")

@router.callback_query(F.data.startswith("approve_"))
async def approve_advertisement(callback: CallbackQuery):
    ad_id = int(callback.data.split("_")[1])
    db = Database()
    try:
        ad = db.get_advertisement(ad_id)
        if ad:
            server = db.get_server(ad[2])
            channel_id = server[2]

            photo_id = ad[4]
            caption = ad[3]

            if photo_id:
                await callback.bot.send_photo(
                    chat_id=channel_id,
                    photo=photo_id,
                    caption=caption
                )
            else:
                await callback.bot.send_message(
                    chat_id=channel_id,
                    text=caption
                )

            db.update_advertisement_status(ad_id, "approved")

            await callback.bot.send_message(
                chat_id=ad[1],
                text="✅ Ваше объявление было *одобрено* и опубликовано!",
                parse_mode="Markdown"
            )

            await callback.message.answer("Объявление одобрено и опубликовано ✅")
            await callback.message.delete()
    finally:
        db.close()


@router.callback_query(F.data.startswith("reject_"))
async def reject_advertisement(callback: CallbackQuery):
    ad_id = int(callback.data.split("_")[1])
    db = Database()
    try:
        ad = db.get_advertisement(ad_id)
        if ad:
            db.update_advertisement_status(ad_id, "rejected")

            await callback.bot.send_message(
                chat_id=ad[1],
                text="❌ Ваше объявление было *отклонено* модератором.",
                parse_mode="Markdown"
            )

            await callback.message.edit_text("Объявление отклонено")
            await callback.message.delete()
    finally:
        db.close()
