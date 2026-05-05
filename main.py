from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.types import MenuButtonWebApp, WebAppInfo
import os

TOKEN = os.environ["TOKEN"]
WEBAPP_URL = os.environ["WEBAPP_URL"]

bot = Bot(token=TOKEN)
dp = Dispatcher()
app = FastAPI()

@dp.message()
async def echo(message: types.Message):
    await message.answer(f"your message : {message.text}")

@app.on_event("startup")
async def on_startup():
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Открыть TrustGram",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    )

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = types.Update(**data)
    await dp.feed_update(bot, update)
    return {"ok": True}