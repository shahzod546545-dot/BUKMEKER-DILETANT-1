from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import json
import os
from pydantic import BaseModel
from typing import Union
app = FastAPI(title="Kids Bet League API")
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print("❌ Ошибка валидации данных:", exc.errors())
    return JSONResponse(
        status_code=422,
        content={"message": "Ошибка в структуре данных", "details": exc.errors()},
    )
# Настройка CORS, чтобы твой HTML-сайт мог свободно делать запросы к Python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "database.json"

# Инициализация пустой базы данных, если файла еще нет
if not os.path.exists(DB_FILE):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump({"users": [], "matches": [], "predictions": []}, f, ensure_ascii=False, indent=4)

def load_db():
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# --- Модели данных (Схемы запросов) ---

class User(BaseModel):
    id: str
    username: str
    name: str
    password: str
    age: Optional[int] = 0
    team: Optional[str] = ""
    points: int = 0
    level: int = 1
    xp: int = 0

class LoginRequest(BaseModel):
    username: str
    password: str

class Match(BaseModel):
    id: int
    team1: str
    team2: str
    date: str
    time: str
    status: str  # 'OPEN' или 'CLOSED'
    score1: Optional[int] = None
    score2: Optional[int] = None

class Prediction(BaseModel):
    match_id: Union[int, str]  # Примет и число, и строку, сервер больше не упадет
    username: str
    home_score: int
    away_score: int

class CalculateMatchRequest(BaseModel):
    matchId: int
    score1: int
    score2: int

class BonusXpRequest(BaseModel):
    userId: str
    xpToAdd: int


# --- Эндпоинты (Маршруты API) ---

# 1. Получить всех пользователей
@app.get("/api/users", response_model=List[User])
def get_users():
    return load_db()["users"]

# 2. Получить все матчи
@app.get("/api/matches", response_model=List[Match])
def get_matches():
    return load_db()["matches"]

# 3. Получить все прогнозы
@app.get("/api/predictions")
def get_predictions():
    db = load_db()
    # Возвращаем массив прогнозов напрямую из базы без принудительной фильтрации
    return db.get("predictions", [])

# 4. Регистрация нового игрока
@app.post("/api/register")
def register_user(user: User):
    db = load_db()
    if any(u["username"].lower() == user.username.lower() for u in db["users"]):
        raise HTTPException(status_code=400, detail="Этот никнейм уже занят!")
    
    db["users"].append(user.dict())
    save_db(db)
    return {"status": "success", "message": "Вы успешно зарегистрированы!"}

# 5. Авторизация (Вход)
@app.post("/api/login")
def login_user(req: LoginRequest):
    db = load_db()
    found_user = next((u for u in db["users"] if u["username"].lower() == req.username.lower() and u["password"] == req.password), None)
    
    if not found_user:
        raise HTTPException(status_code=401, detail="Неверный никнейм или пароль")
    return found_user

# 6. Сохранение или обновление прогноза
@app.post("/api/predictions")
def predict_match(prediction_data: dict):
    db = load_db()
    
    # Это напечатает в терминале ТОЧНЫЙ состав данных с сайта
    print("\n--- С ФРОНТЕНДА ПРИЛЕТЕЛИ ЭТИ ДАННЫЕ: ---")
    print(prediction_data)
    print("----------------------------------------\n")
    
    # Просто сохраняем то, что пришло
    db["predictions"].append(prediction_data)
    save_db(db)
    
    return {"status": "success", "message": "Прогноз успешно принят сервером!"}
    
    # Проверяем, закрыт ли матч для прогнозов
    match = next((m for m in db["matches"] if m["id"] == pred.matchId), None)
    if match and match["status"] == "CLOSED":
        raise HTTPException(status_code=400, detail="Этот матч уже рассчитан, прогнозы закрыты!")

    # Ищем, делал ли этот юзер прогноз на этот матч ранее
    idx = next((i for i, p in enumerate(db["predictions"]) if p["userId"] == pred.userId and p["matchId"] == pred.matchId), -1)
    
    if idx > -1:
        db["predictions"][idx] = pred.dict()
    else:
        db["predictions"].append(pred.dict())
        
    save_db(db)
    return {"status": "success"}

# 7. Добавление нового матча (Админка)
@app.post("/api/matches")
def add_match(match: Match):
    db = load_db()
    db["matches"].append(match.model_dump())
    save_db(db)
    return {"status": "success"}

# 8. Расчет матча и начисление очков/XP (Админка)
@app.post("/api/matches/calculate")
def calculate_match(req: CalculateMatchRequest):
    db = load_db()
    
    match = next((m for m in db["matches"] if m["id"] == req.matchId), None)
    if not match:
        raise HTTPException(status_code=404, detail="Матч не найден")
        
    match["score1"] = req.score1
    match["score2"] = req.score2
    match["status"] = "CLOSED"

    # Фильтруем прогнозы только для этого матча
    match_preds = [p for p in db["predictions"] if p["matchId"] == req.matchId]

    for pred in match_preds:
        user = next((u for u in db["users"] if u["id"] == pred["userId"]), None)
        if user:
            earned = 0
            # Считаем очки лиги
            if pred["predictScore1"] == req.score1 and pred["predictScore2"] == req.score2:
                earned = 5
            elif (pred["predictScore1"] > pred["predictScore2"] and req.score1 > req.score2) or \
                 (pred["predictScore1"] < pred["predictScore2"] and req.score1 < req.score2):
                earned = 3
            elif pred["predictScore1"] == pred["predictScore2"] and req.score1 == req.score2:
                earned = 2

            user["points"] += earned
            # Добавляем базовый XP за участие (20) + бонус за точность
            user["xp"] += 20 + (earned * 5)
            
            # Повышение уровня при достижении 100 XP
            while user["xp"] >= 100:
                user["level"] += 1
                user["xp"] -= 100

    save_db(db)
    return {"status": "success", "message": "Матч рассчитан, очки обновлены."}

# 9. Бонусное колесо фортуны (Добавление XP)
@app.post("/api/users/bonus-xp")
def add_bonus_xp(req: BonusXpRequest):
    db = load_db()
    user = next((u for u in db["users"] if u["id"] == req.userId), None)
    
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
        
    user["xp"] += req.xpToAdd
    while user["xp"] >= 100:
        user["level"] += 1
        user["xp"] -= 100
        
    save_db(db)
    return {"status": "success", "level": user["level"], "xp": user["xp"]}


if __name__ == "__main__":
    import uvicorn
    # Запускаем локальный веб-сервер на порту 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)