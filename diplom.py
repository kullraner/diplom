import pandas as pd
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func
import uvicorn
from typing import List, Optional

# --- КОНФІГУРАЦІЯ БД ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./university_admission.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- МОДЕЛІ БД (SQLAlchemy) ---
class Specialty(Base):
    __tablename__ = "specialties"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    code = Column(String, unique=True)
    quota = Column(Integer, default=5) # Кількість місць

class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True, index=True)
    applicant_name = Column(String)
    specialty_id = Column(Integer, ForeignKey("specialties.id"))
    score = Column(Float)
    priority = Column(Integer)
    status = Column(String, default="На розгляді") # Нове поле для статусу
    created_at = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(bind=engine)

# --- СХЕМИ ВАЛІДАЦІЇ (Pydantic) ---
class ApplicationCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=50)
    spec_id: int
    score: float = Field(..., ge=100, le=200)
    priority: int = Field(..., ge=1, le=5)

# --- ЛОГІКА ДОДАТКУ ---
app = FastAPI(title="Система Приймальної Комісії")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.on_event("startup")
def init_db():
    db = SessionLocal()
    if not db.query(Specialty).first():
        db.add_all([
            Specialty(name="Комп'ютерні науки", code="122", quota=3),
            Specialty(name="Інженерія програмного забезпечення", code="121", quota=2),
            Specialty(name="Кібербезпека", code="125", quota=2)
        ])
        db.commit()
    db.close()

@app.get("/api/ranking/{spec_id}")
async def get_ranking(spec_id: int, db: Session = Depends(get_db)):
    # Використовуємо Pandas для інтелектуального ранжування
    query = db.query(Application).filter(Application.specialty_id == spec_id).all()
    if not query: return []
    
    df = pd.DataFrame([
        {"id": a.id, "name": a.applicant_name, "score": a.score, 
         "priority": a.priority, "time": a.created_at, "status": a.status} 
        for a in query
    ])
    
    # Розрахунок з урахуванням регіонального коефіцієнта (наприклад, 1.02)
    df['final_score'] = df['score'] * 1.02 
    
    # Сортування за балом, пріоритетом та часом
    df_sorted = df.sort_values(
        by=["final_score", "priority", "time"], 
        ascending=[False, True, True]
    ).reset_index(drop=True)
    
    # Додаємо автоматичну позначку "Рекомендовано", якщо в межах квоти
    spec = db.query(Specialty).get(spec_id)
    df_sorted['recommendation'] = df_sorted.index < spec.quota
    
    return df_sorted.to_dict(orient="records")

@app.post("/api/submit")
async def submit(data: ApplicationCreate, db: Session = Depends(get_db)):
    new_app = Application(
        applicant_name=data.name, 
        specialty_id=data.spec_id, 
        score=data.score, 
        priority=data.priority
    )
    db.add(new_app)
    db.commit()
    return {"status": "success", "message": "Заяву зареєстровано в системі"}

@app.get("/api/specs")
async def get_specs(db: Session = Depends(get_db)):
    return db.query(Specialty).all()

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <!DOCTYPE html>
    <html lang="uk">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ВСТУП 2026 | Система управління</title>
        <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
        <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
        <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            body { font-family: 'Inter', sans-serif; }
            .glass { background: rgba(255, 255, 255, 0.9); backdrop-filter: blur(10px); }
            .row-anim { transition: all 0.3s ease; }
            .row-anim:hover { transform: scale(1.01); background-color: #f8fafc; }
        </style>
    </head>
    <body class="bg-slate-50 text-slate-900">
        <div id="root"></div>
        <script type="text/babel">
            const { useState, useEffect } = React;

            function AdmissionApp() {
                const [specs, setSpecs] = useState([]);
                const [ranking, setRanking] = useState([]);
                const [selectedSpec, setSelectedSpec] = useState(null);
                const [form, setForm] = useState({ name: '', score: 150, priority: 1 });
                const [loading, setLoading] = useState(false);

                useEffect(() => {
                    fetch('/api/specs').then(res => res.json()).then(data => { 
                        setSpecs(data); 
                        if(data.length) {
                            setSelectedSpec(data[0].id);
                            loadRanking(data[0].id);
                        }
                    });
                }, []);

                const loadRanking = async (id) => {
                    setLoading(true);
                    const res = await fetch('/api/ranking/' + id);
                    const data = await res.json();
                    setRanking(data);
                    setLoading(false);
                };

                const send = async (e) => {
                    e.preventDefault();
                    const res = await fetch('/api/submit', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({...form, spec_id: selectedSpec})
                    });
                    if(res.ok) {
                        alert("Заяву успішно подано!");
                        loadRanking(selectedSpec);
                    }
                };

                return (
                    <div className="min-h-screen p-4 md:p-8">
                        <header className="max-w-6xl mx-auto mb-10 flex justify-between items-center">
                            <div>
                                <h1 className="text-4xl font-extrabold text-blue-900 tracking-tight">ВСТУП <span className="text-blue-600">2026</span></h1>
                                <p className="text-slate-500">Автоматизована система приймальної комісії</p>
                            </div>
                            <div className="bg-blue-100 text-blue-700 px-4 py-2 rounded-full font-semibold text-sm">
                                Асинхронний режим: FastAPI + Pandas
                            </div>
                        </header>

                        <main className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-8">
                            {/* Форма подачі */}
                            <div className="lg:col-span-4">
                                <div className="glass p-6 rounded-2xl shadow-xl border border-white">
                                    <h2 className="text-xl font-bold mb-6 flex items-center">
                                        <span className="bg-blue-600 w-2 h-6 rounded mr-3"></span>
                                        Подача заяви
                                    </h2>
                                    <form onSubmit={send} className="space-y-4">
                                        <div>
                                            <label className="block text-sm font-medium mb-1">Прізвище та ім'я</label>
                                            <input className="w-full border-slate-200 border rounded-lg p-3 focus:ring-2 focus:ring-blue-500 outline-none" 
                                                required onChange={e => setForm({...form, name: e.target.value})} />
                                        </div>
                                        <div className="grid grid-cols-2 gap-4">
                                            <div>
                                                <label className="block text-sm font-medium mb-1">Бал НМТ</label>
                                                <input type="number" step="0.1" className="w-full border-slate-200 border rounded-lg p-3" 
                                                    onChange={e => setForm({...form, score: parseFloat(e.target.value)})} />
                                            </div>
                                            <div>
                                                <label className="block text-sm font-medium mb-1">Пріоритет</label>
                                                <input type="number" min="1" max="5" className="w-full border-slate-200 border rounded-lg p-3" 
                                                    onChange={e => setForm({...form, priority: parseInt(e.target.value)})} />
                                            </div>
                                        </div>
                                        <div>
                                            <label className="block text-sm font-medium mb-1">Спеціальність</label>
                                            <select className="w-full border-slate-200 border rounded-lg p-3 bg-white" 
                                                value={selectedSpec} onChange={e => {setSelectedSpec(e.target.value); loadRanking(e.target.value);}}>
                                                {specs.map(s => <option key={s.id} value={s.id}>{s.code} | {s.name}</option>)}
                                            </select>
                                        </div>
                                        <button className="w-full bg-blue-600 text-white font-bold py-4 rounded-xl hover:bg-blue-700 transition-colors shadow-lg shadow-blue-200">
                                            Зареєструвати заяву
                                        </button>
                                    </form>
                                </div>
                            </div>

                            {/* Таблиця рейтингу */}
                            <div className="lg:col-span-8">
                                <div className="glass p-6 rounded-2xl shadow-xl border border-white">
                                    <div className="flex justify-between items-center mb-6">
                                        <h2 className="text-xl font-bold flex items-center">
                                            <span className="bg-emerald-500 w-2 h-6 rounded mr-3"></span>
                                            Рейтинговий список
                                        </h2>
                                        <span className="text-xs text-slate-400">Оновлено: щойно</span>
                                    </div>
                                    
                                    <div className="overflow-x-auto">
                                        <table className="w-full text-left">
                                            <thead>
                                                <tr className="text-slate-400 text-sm uppercase tracking-wider border-b">
                                                    <th className="pb-4 font-medium">№</th>
                                                    <th className="pb-4 font-medium">Абітурієнт</th>
                                                    <th className="pb-4 font-medium text-center">Пр.</th>
                                                    <th className="pb-4 font-medium text-right">Бал (+РК)</th>
                                                    <th className="pb-4 font-medium text-right">Статус</th>
                                                </tr>
                                            </thead>
                                            <tbody className="divide-y divide-slate-100">
                                                {ranking.map((r, i) => (
                                                    <tr key={i} className="row-anim">
                                                        <td className="py-4 font-bold text-slate-400">{i+1}</td>
                                                        <td className="py-4">
                                                            <div className="font-semibold">{r.name}</div>
                                                            <div className="text-xs text-slate-400 italic">Заява #{r.id}</div>
                                                        </td>
                                                        <td className="py-4 text-center">
                                                            <span className="bg-slate-100 px-2 py-1 rounded text-xs font-bold">{r.priority}</span>
                                                        </td>
                                                        <td className="py-4 text-right font-bold text-blue-600">
                                                            {r.final_score.toFixed(2)}
                                                        </td>
                                                        <td className="py-4 text-right">
                                                            {r.recommendation ? (
                                                                <span className="bg-emerald-100 text-emerald-700 px-3 py-1 rounded-full text-xs font-bold">
                                                                    Рекомендовано
                                                                </span>
                                                            ) : (
                                                                <span className="bg-slate-100 text-slate-500 px-3 py-1 rounded-full text-xs font-bold">
                                                                    Допущено
                                                                </span>
                                                            )}
                                                        </td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                        {ranking.length === 0 && !loading && (
                                            <div className="text-center py-10 text-slate-400">Заяв поки немає. Будьте першим!</div>
                                        )}
                                    </div>
                                </div>
                            </div>
                        </main>
                    </div>
                );
            }
            ReactDOM.createRoot(document.getElementById('root')).render(<AdmissionApp />);
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    # Налаштування хоста та порту для диплома
    uvicorn.run("diplom:app", host="127.0.0.1", port=8080, reload=True)