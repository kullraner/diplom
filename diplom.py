import pandas as pd
import io
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
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

ADMIN_EMAIL = "kullraner128@gmail.com"
ADMIN_PASSWORD = "17904880"
ADMIN_TOKEN = "secure_token_2026_admin"

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
        if not db.query(Specialty).first():
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
    name: str = Field(..., min_length=2)
    spec_id: int
    score: float = Field(..., ge=0, le=100)
    priority: int = Field(..., ge=1, le=5)

class AdminLogin(BaseModel):
    email: str
    password: str

@app.post("/api/admin/login")
async def admin_login(credentials: AdminLogin):
    if credentials.email == ADMIN_EMAIL and credentials.password == ADMIN_PASSWORD:
        return {"status": "success", "token": ADMIN_TOKEN}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.delete("/api/admin/application/{app_id}")
async def delete_application(app_id: int, token: str, db: Session = Depends(get_db_session)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403)
    item = db.query(Application).filter(Application.id == app_id).first()
    if item:
        db.delete(item)
        db.commit()
    return {"status": "success"}

@app.get("/api/export/{spec_id}")
async def export_ranking(spec_id: int, db: Session = Depends(get_db_session)):
    query = db.query(Application).filter(Application.specialty_id == spec_id).all()
    if not query: raise HTTPException(status_code=404)
    df = pd.DataFrame([{"Rank": i+1, "Name": a.applicant_name, "Score": a.score, "Priority": a.priority} for i, a in enumerate(query)])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=Ranking_{spec_id}.xlsx"})

@app.get("/api/ranking/{spec_id}")
async def get_ranking(spec_id: int, db: Session = Depends(get_db_session)):
    query = db.query(Application).filter(Application.specialty_id == spec_id).all()
    df = pd.DataFrame([{"id": a.id, "name": a.applicant_name, "score": a.score, "priority": a.priority} for a in query])
    if df.empty: return []
    df['final_score'] = df['score'] * 1.02
    df_sorted = df.sort_values(by=["final_score", "priority"], ascending=[False, True]).reset_index(drop=True)
    df_sorted['status'] = df_sorted['final_score'].apply(lambda s: "Budget" if s > 70 else "Contract")
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
    </head>
    <body class="bg-slate-950 text-white font-['Inter']">
        <div id="root"></div>
        <script type="text/babel">
            const { useState, useEffect, useMemo, useRef } = React;
            function App() {
                const [specs, setSpecs] = useState([]);
                const [ranking, setRanking] = useState([]);
                const [sel, setSel] = useState("");
                const [f, setF] = useState({ name: '', score: 100, priority: 1 });
                const [adminToken, setAdminToken] = useState(null);
                const [isLoginOpen, setIsLoginOpen] = useState(false);
                const [cred, setCred] = useState({ email: '', password: '' });
                const chartRef = useRef(null);
                const chartInstance = useRef(null);

                useEffect(() => {
                    fetch('/api/specs').then(r => r.json()).then(d => { setSpecs(d); if(d.length) { setSel(d[0].id); load(d[0].id); } });
                }, []);

                useEffect(() => {
                    if (chartRef.current && ranking.length > 0) {
                        const ctx = chartRef.current.getContext('2d');
                        if (chartInstance.current) chartInstance.current.destroy();
                        chartInstance.current = new Chart(ctx, {
                            type: 'bar',
                            data: {
                                labels: ranking.slice(0,5).map(r => r.name.split(' ')[0]),
                                datasets: [{ label: 'Score', data: ranking.slice(0,5).map(r => r.final_score), backgroundColor: '#6366f1', borderRadius: 8 }]
                            },
                            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { display: false }, x: { grid: { display: false }, ticks: { color: '#94a3b8' } } } }
                        });
                    }
                }, [ranking]);

                const load = (id) => fetch('/api/ranking/'+id).then(r => r.json()).then(setRanking);

                const login = (e) => {
                    e.preventDefault();
                    fetch('/api/admin/login', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(cred) })
                    .then(r => r.json()).then(d => { if(d.token) { setAdminToken(d.token); setIsLoginOpen(false); } else alert('Invalid Credentials'); });
                };

                const del = (id) => {
                    if(confirm('Delete this application?')) {
                        fetch(`/api/admin/application/${id}?token=${adminToken}`, { method: 'DELETE' }).then(() => load(sel));
                    }
                };

                return (
                    <div className="max-w-7xl mx-auto p-8">
                        <header className="flex justify-between items-center mb-12">
                            <h1 className="text-4xl font-black italic text-indigo-500 underline decoration-indigo-800">EduPortal PRO</h1>
                            <div className="flex gap-4">
                                {adminToken ? 
                                    <button onClick={() => setAdminToken(null)} className="bg-slate-800 px-6 py-2 rounded-xl text-xs font-bold uppercase hover:bg-slate-700">Logout Admin</button> :
                                    <button onClick={() => setIsLoginOpen(true)} className="bg-rose-600 px-6 py-2 rounded-xl text-xs font-bold uppercase shadow-lg shadow-rose-500/20 hover:bg-rose-700">Admin Panel</button>
                                }
                            </div>
                        </header>

                        {isLoginOpen && (
                            <div className="fixed inset-0 bg-black/90 flex items-center justify-center z-50 p-4">
                                <div className="bg-slate-900 p-10 rounded-3xl border border-slate-800 w-full max-w-md shadow-2xl">
                                    <h2 className="text-2xl font-black mb-6 text-indigo-400">Admin Access</h2>
                                    <form onSubmit={login} className="space-y-4">
                                        <input type="email" placeholder="Email" className="w-full bg-slate-800 p-4 rounded-xl outline-none border border-transparent focus:border-indigo-500" onChange={e => setCred({...cred, email: e.target.value})} />
                                        <input type="password" placeholder="Password" className="w-full bg-slate-800 p-4 rounded-xl outline-none border border-transparent focus:border-indigo-500" onChange={e => setCred({...cred, password: e.target.value})} />
                                        <button className="w-full bg-indigo-600 p-4 rounded-xl font-bold uppercase hover:bg-indigo-700">Login</button>
                                        <button type="button" onClick={() => setIsLoginOpen(false)} className="w-full text-slate-500 text-sm hover:text-white mt-2">Close</button>
                                    </form>
                                </div>
                            </div>
                        )}

                        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
                            <div className="lg:col-span-4 space-y-6">
                                <div className="bg-slate-900 p-8 rounded-[2.5rem] border border-slate-800 shadow-2xl">
                                    <h2 className="text-xl font-black mb-6 uppercase tracking-widest text-slate-400">Application Form</h2>
                                    <form onSubmit={(e) => { 
                                        e.preventDefault(); 
                                        fetch('/api/submit', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...f, spec_id: parseInt(sel)}) })
                                        .then(r => { if(r.ok) { load(sel); setF({...f, name: ''}); } else alert('Error: Check score (0-100)'); });
                                    }} className="space-y-4">
                                        <input placeholder="Student Full Name" value={f.name} className="w-full bg-slate-800 p-4 rounded-2xl outline-none border-2 border-transparent focus:border-indigo-500" onChange={e => setF({...f, name: e.target.value})} />
                                        <div className="flex gap-4">
                                            <div className="w-full">
                                                <label className="text-[10px] text-slate-500 font-bold uppercase ml-1 mb-1 block">Score (0-100)</label>
                                                <input type="number" placeholder="0-100" className="w-full bg-slate-800 p-4 rounded-2xl outline-none" onChange={e => setF({...f, score: parseFloat(e.target.value)})} />
                                            </div>
                                            <div className="w-32">
                                                <label className="text-[10px] text-slate-500 font-bold uppercase ml-1 mb-1 block">Priority</label>
                                                <select className="w-full bg-slate-800 p-4 rounded-2xl outline-none" onChange={e => setF({...f, priority: parseInt(e.target.value)})}>
                                                    {[1,2,3,4,5].map(p => <option key={p} value={p}>P:{p}</option>)}
                                                </select>
                                            </div>
                                        </div>
                                        <select className="w-full bg-slate-800 p-4 rounded-2xl outline-none" value={sel} onChange={e => { setSel(e.target.value); load(e.target.value); }}>
                                            {specs.map(s => <option key={s.id} value={s.id}>{s.code} | {s.name}</option>)}
                                        </select>
                                        <button className="w-full bg-indigo-600 p-5 rounded-2xl font-black uppercase shadow-xl shadow-indigo-500/20 hover:bg-indigo-700 active:scale-95 transition-all">Register Applicant</button>
                                    </form>
                                </div>
                                <div className="bg-slate-900 p-8 rounded-[2.5rem] border border-slate-800 h-64">
                                    <p className="text-[10px] text-slate-500 font-bold uppercase mb-4 text-center">Top 5 Performance</p>
                                    <canvas ref={chartRef}></canvas>
                                </div>
                            </div>

                            <div className="lg:col-span-8 bg-slate-900 p-10 rounded-[2.5rem] border border-slate-800 shadow-2xl overflow-hidden">
                                <div className="flex justify-between items-center mb-8 gap-4">
                                    <div className="relative flex-1">
                                        <input placeholder="Search applicants..." className="bg-slate-800 pl-12 pr-6 py-4 rounded-2xl outline-none w-full border border-transparent focus:border-indigo-500" onChange={e => {
                                            const val = e.target.value.toLowerCase();
                                            if(!val) load(sel);
                                            else setRanking(ranking.filter(r => r.name.toLowerCase().includes(val)));
                                        }} />
                                        <span className="absolute left-4 top-4 opacity-30 text-xl">🔍</span>
                                    </div>
                                    <button onClick={() => window.location.href = `/api/export/${sel}`} className="bg-emerald-600 px-8 py-4 rounded-2xl font-bold text-xs uppercase tracking-widest shadow-lg shadow-emerald-500/20 hover:bg-emerald-700">Export Excel</button>
                                </div>
                                <div className="overflow-x-auto">
                                    <table className="w-full">
                                        <thead>
                                            <tr className="text-slate-500 text-[10px] font-black uppercase tracking-widest border-b border-slate-800">
                                                <th className="pb-4 text-left px-2">Rank</th>
                                                <th className="pb-4 text-left">Applicant Name</th>
                                                <th className="pb-4 text-center">Final Score</th>
                                                <th className="pb-4 text-right">Action</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-slate-800">
                                            {ranking.length > 0 ? ranking.map((r, idx) => (
                                                <tr key={r.id} className="hover:bg-indigo-500/5 transition-all">
                                                    <td className="py-5 font-black text-slate-500 px-2">#{idx+1}</td>
                                                    <td className="py-5 font-bold">{r.name} <span className="text-[9px] text-indigo-400 bg-indigo-400/10 px-2 py-0.5 rounded-md ml-2">PRIORITY {r.priority}</span></td>
                                                    <td className="py-5 text-center font-black text-indigo-500 text-lg">{r.final_score.toFixed(1)}</td>
                                                    <td className="py-5 text-right">
                                                        {adminToken ? 
                                                            <button onClick={() => del(r.id)} className="bg-rose-500/10 text-rose-500 px-4 py-2 rounded-lg text-[10px] font-black uppercase hover:bg-rose-500 hover:text-white transition-all">Delete Record</button> :
                                                            <span className={`text-[10px] px-3 py-1 rounded-lg font-black uppercase tracking-tighter ${r.status === 'Budget' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'}`}>{r.status}</span>
                                                        }
                                                    </td>
                                                </tr>
                                            )) : (
                                                <tr><td colSpan="4" className="py-10 text-center text-slate-500 font-bold italic uppercase tracking-widest">No candidates registered</td></tr>
                                            )}
                                        </tbody>
                                    </table>
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
    uvicorn.run("diplom:app", host="0.0.0.0", port=8080)
