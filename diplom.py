import pandas as pd
import io
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from sqlalchemy.sql import func
import uvicorn
from contextlib import asynccontextmanager

SQLALCHEMY_DATABASE_URL = "sqlite:///./university_admission.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

class Specialty(Base):
    __tablename__ = "specialties"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    code = Column(String, unique=True)
    quota = Column(Integer, default=5)

class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True, index=True)
    applicant_name = Column(String)
    specialty_id = Column(Integer, ForeignKey("specialties.id"))
    score = Column(Float)
    priority = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(bind=engine)

def get_db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        db.query(Specialty).delete() 
        db.add_all([
            Specialty(name="Computer Science", code="122", quota=10),
            Specialty(name="Software Engineering", code="121", quota=8),
            Specialty(name="Cybersecurity", code="125", quota=5),
            Specialty(name="Applied Mathematics", code="113", quota=4),
            Specialty(name="Computer Engineering", code="123", quota=7),
            Specialty(name="System Analysis", code="124", quota=3),
            Specialty(name="Information Systems & Tech", code="126", quota=6),
            Specialty(name="Automation & Robotics", code="174", quota=5),
            Specialty(name="Telecommunications", code="172", quota=4),
            Specialty(name="Power Engineering", code="141", quota=6),
            Specialty(name="Biomedical Engineering", code="163", quota=3),
            Specialty(name="Micro & Nanosystems", code="153", quota=2)
        ])
        db.commit()
    finally:
        db.close()
    yield

app = FastAPI(lifespan=lifespan)

class ApplicationCreate(BaseModel):
    name: str
    spec_id: int
    score: float
    priority: int

@app.get("/api/export/{spec_id}")
async def export_ranking(spec_id: int, db: Session = Depends(get_db_session)):
    query = db.query(Application).filter(Application.specialty_id == spec_id).all()
    if not query: 
        raise HTTPException(status_code=404, detail="No data")
    
    df = pd.DataFrame([
        {"Rank": i+1, "Name": a.applicant_name, "Base Score": a.score, "Priority": a.priority, "Final Score": round(a.score * 1.02, 1)} 
        for i, a in enumerate(query)
    ])
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Ranking')
    output.seek(0)
    
    return StreamingResponse(
        output, 
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=Ranking_Spec_{spec_id}.xlsx"}
    )

@app.get("/api/ranking/{spec_id}")
async def get_ranking(spec_id: int, db: Session = Depends(get_db_session)):
    query = db.query(Application).filter(Application.specialty_id == spec_id).all()
    if not query: return []
    
    df = pd.DataFrame([
        {"id": a.id, "name": a.applicant_name, "score": a.score, "priority": a.priority} 
        for a in query
    ])
    df['final_score'] = df['score'] * 1.02 
    df_sorted = df.sort_values(by=["final_score", "priority"], ascending=[False, True]).reset_index(drop=True)
    
    def assign_status(score):
        if score < 30: return "Rejected"
        elif 30 <= score < 70: return "Contract"
        else: return "Budget"

    df_sorted['status'] = df_sorted['final_score'].apply(assign_status)
    return df_sorted.to_dict(orient="records")

@app.post("/api/submit")
async def submit(data: ApplicationCreate, db: Session = Depends(get_db_session)):
    new_app = Application(applicant_name=data.name, specialty_id=data.spec_id, score=data.score, priority=data.priority)
    db.add(new_app)
    db.commit()
    return {"status": "success"}

@app.get("/api/specs")
async def get_specs(db: Session = Depends(get_db_session)):
    return db.query(Specialty).all()

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>EduPortal PRO 2026</title>
        <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
        <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
        <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap" rel="stylesheet">
        <style> 
            body { font-family: 'Inter', sans-serif; transition: all 0.4s ease; }
            .live-dot { width: 10px; height: 10px; background: #10b981; border-radius: 50%; display: inline-block; animation: blink 1.5s infinite; }
            @keyframes blink { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.3; transform: scale(1.3); } }
        </style>
    </head>
    <body>
        <div id="root"></div>
        <script type="text/babel">
            const { useState, useEffect, useMemo, useRef } = React;

            function App() {
                const [specs, setSpecs] = useState([]);
                const [ranking, setRanking] = useState([]);
                const [sel, setSel] = useState("");
                const [f, setF] = useState({ name: '', score: 100, priority: 1 });
                const [theme, setTheme] = useState('dark');
                const [searchTerm, setSearchTerm] = useState('');
                const [lastUpdate, setLastUpdate] = useState(new Date().toLocaleTimeString());
                
                const chartRef = useRef(null);
                const chartInstance = useRef(null);

                useEffect(() => {
                    fetch('/api/specs').then(r => r.json()).then(d => { 
                        setSpecs(d); 
                        if(d.length) { setSel(d[0].id); load(d[0].id); }
                    });
                }, []);

                useEffect(() => {
                    if (chartRef.current && ranking.length > 0) {
                        const ctx = chartRef.current.getContext('2d');
                        if (chartInstance.current) chartInstance.current.destroy();
                        
                        const topData = ranking.slice(0, 5);
                        chartInstance.current = new Chart(ctx, {
                            type: 'bar',
                            data: {
                                labels: topData.map(r => r.name.split(' ')[0]),
                                datasets: [{
                                    label: 'Final Score',
                                    data: topData.map(r => r.final_score),
                                    backgroundColor: '#6366f1',
                                    borderRadius: 12,
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                scales: { 
                                    y: { beginAtZero: true, max: 110, ticks: { display: false }, grid: { display: false } }, 
                                    x: { grid: { display: false }, ticks: { color: theme === 'dark' ? '#94a3b8' : '#64748b' } } 
                                },
                                plugins: { legend: { display: false } }
                            }
                        });
                    }
                }, [ranking, theme]);

                const load = (id) => {
                    fetch('/api/ranking/'+id).then(r => r.json()).then(d => {
                        setRanking(d);
                        setLastUpdate(new Date().toLocaleTimeString());
                    });
                };

                const filteredRanking = ranking.filter(r => 
                    r.name.toLowerCase().includes(searchTerm.toLowerCase())
                );

                const stats = useMemo(() => {
                    if(!ranking.length) return { total: 0, avg: 0, min: 0 };
                    const scores = ranking.map(r => r.final_score);
                    return {
                        total: ranking.length,
                        avg: (scores.reduce((a,b) => a+b, 0) / ranking.length).toFixed(1),
                        min: Math.min(...scores).toFixed(1)
                    };
                }, [ranking]);

                const isDark = theme === 'dark';
                const bgClass = isDark ? "bg-slate-950 text-white" : "bg-slate-50 text-slate-900";
                const cardClass = isDark ? "bg-slate-900 border-slate-800 shadow-2xl" : "bg-white border-slate-200 shadow-sm";
                const inputClass = isDark ? "bg-slate-800 text-white border-slate-700" : "bg-slate-100 text-slate-900 border-transparent";

                return (
                    <div className={`min-h-screen p-4 md:p-8 transition-colors duration-500 ${bgClass}`}>
                        <div className="max-w-7xl mx-auto relative z-10">
                            <header className="mb-10 flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
                                <div>
                                    <h1 className={`text-5xl font-black tracking-tight ${isDark ? "text-white" : "text-slate-900"}`}>
                                        EduPortal <span className="text-indigo-600 italic">PRO</span>
                                    </h1>
                                    <div className="flex items-center gap-3 mt-2">
                                        <span className="live-dot"></span>
                                        <span className="text-[11px] font-black text-slate-500 uppercase tracking-widest">
                                            Admission Live Status • {lastUpdate}
                                        </span>
                                    </div>
                                </div>
                                <button onClick={() => setTheme(isDark ? 'light' : 'dark')} className={`px-6 py-3 rounded-2xl font-bold text-xs uppercase tracking-widest transition-all ${isDark ? "bg-slate-800 border border-slate-700" : "bg-white border border-slate-200 shadow-sm"}`}>
                                    {isDark ? "☀️ Light Mode" : "🌙 Dark Mode"}
                                </button>
                            </header>

                            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10">
                                {[
                                    {label: "Total Apps", val: stats.total, color: "text-indigo-500"},
                                    {label: "Avg Score", val: stats.avg, color: "text-blue-500"},
                                    {label: "Min Passing", val: stats.min, color: "text-emerald-500"}
                                ].map((s, idx) => (
                                    <div key={idx} className={`${cardClass} p-8 rounded-[2rem] border relative overflow-hidden group`}>
                                        <div className={`absolute top-0 left-0 w-2 h-full ${s.color.replace('text', 'bg')}`}></div>
                                        <p className="text-slate-500 text-[10px] font-black uppercase tracking-widest mb-2">{s.label}</p>
                                        <p className={`text-4xl font-black ${s.color}`}>{s.val}</p>
                                    </div>
                                ))}
                            </div>

                            <div className="grid grid-cols-1 lg:grid-cols-12 gap-10">
                                <div className="lg:col-span-4 space-y-8">
                                    <div className={`${cardClass} p-8 rounded-[2.5rem] border`}>
                                        <h2 className="text-2xl font-black mb-8 tracking-tight">Register</h2>
                                        <form onSubmit={(e) => { e.preventDefault(); if(!f.name) return; fetch('/api/submit', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...f, spec_id: parseInt(sel)})}).then(() => load(sel)); }} className="space-y-5">
                                            <input placeholder="Full Name" className={`w-full p-5 rounded-2xl outline-none border-2 focus:border-indigo-500 transition-all ${inputClass}`} onChange={e => setF({...f, name: e.target.value})} />
                                            <div className="grid grid-cols-2 gap-4">
                                                <input type="number" placeholder="Score" className={`w-full p-5 rounded-2xl border-2 outline-none ${inputClass}`} onChange={e => setF({...f, score: parseFloat(e.target.value)})} />
                                                <select className={`w-full p-5 rounded-2xl border-2 outline-none ${inputClass}`} value={f.priority} onChange={e => setF({...f, priority: parseInt(e.target.value)})}>
                                                    {[1,2,3,4,5].map(p => <option key={p} value={p}>Rank {p}</option>)}
                                                </select>
                                            </div>
                                            <select className={`w-full p-5 rounded-2xl border-2 outline-none ${inputClass}`} value={sel} onChange={e => {setSel(e.target.value); load(e.target.value);}}>
                                                {specs.map(s => <option key={s.id} value={s.id}>{s.code} | {s.name}</option>)}
                                            </select>
                                            <button className="w-full bg-indigo-600 text-white p-6 rounded-[1.5rem] font-black text-sm uppercase tracking-widest hover:bg-indigo-700 shadow-xl transition-all">Submit Application</button>
                                        </form>
                                    </div>
                                    <div className={`${cardClass} p-8 rounded-[2.5rem] border h-72`}>
                                        <h3 className="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-6 text-center">Score Analytics (Top 5)</h3>
                                        <div className="h-44"><canvas ref={chartRef}></canvas></div>
                                    </div>
                                </div>

                                <div className={`lg:col-span-8 p-10 rounded-[2.5rem] border transition-all ${cardClass}`}>
                                    <div className="flex flex-col md:flex-row justify-between items-center mb-10 gap-6">
                                        <div className="relative flex-1 w-full">
                                            <input type="text" placeholder="Search by name..." className={`w-full p-5 pl-14 rounded-2xl border-2 outline-none focus:border-indigo-500 ${inputClass}`} value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} />
                                            <span className="absolute left-6 top-6 opacity-40">🔍</span>
                                        </div>
                                        <button onClick={() => window.location.href = `/api/export/${sel}`} className="bg-emerald-600 text-white px-8 py-5 rounded-2xl font-black text-xs uppercase tracking-widest hover:bg-emerald-700 transition-all flex items-center gap-3">
                                            <span>📄</span> Export Excel
                                        </button>
                                    </div>
                                    <div className="overflow-x-auto">
                                        <table className="w-full text-left">
                                            <thead>
                                                <tr className="text-slate-500 text-[11px] font-black uppercase tracking-[0.2em] border-b border-slate-100 dark:border-slate-800">
                                                    <th className="pb-6">Rank</th>
                                                    <th className="pb-6">Student</th>
                                                    <th className="pb-6 text-center">Final Score</th>
                                                    <th className="pb-6 text-right">Status</th>
                                                </tr>
                                            </thead>
                                            <tbody className={`divide-y ${isDark ? "divide-slate-800" : "divide-slate-100"}`}>
                                                {filteredRanking.map((r, i) => (
                                                    <tr key={i} className="hover:bg-indigo-600/[0.03] transition-all">
                                                        <td className="py-6 font-black text-slate-300">#{(ranking.indexOf(r)) + 1}</td>
                                                        <td className={`py-6 font-bold ${isDark ? "text-slate-300" : "text-slate-800"}`}>{r.name} <span className="text-[10px] bg-indigo-600/10 text-indigo-500 px-2 py-1 rounded-lg ml-3 border border-indigo-500/10">PR: {r.priority}</span></td>
                                                        <td className="py-6 text-center font-black text-indigo-600 text-lg">{r.final_score.toFixed(1)}</td>
                                                        <td className="py-6 text-right">
                                                            <span className={`text-[10px] font-black uppercase px-4 py-2 rounded-xl border-2 ${
                                                                r.status === 'Budget' ? "text-emerald-500 bg-emerald-500/5 border-emerald-500/20" :
                                                                r.status === 'Contract' ? "text-amber-500 bg-amber-500/5 border-amber-500/20" : 
                                                                "text-rose-500 bg-rose-500/5 border-rose-500/20"
                                                            }`}>{r.status}</span>
                                                        </td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                );
            }
            ReactDOM.createRoot(document.getElementById('root')).render(<App />);
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run("diplom:app", host="127.0.0.1", port=8080, reload=True)
