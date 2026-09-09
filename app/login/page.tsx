"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";

export default function Login() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const router = useRouter();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim()) {
      setError("请输入密码");
      return;
    }
    document.cookie = `bdsm_auth=${encodeURIComponent(password)}; path=/; max-age=31536000; SameSite=Lax`;
    router.push("/");
    router.refresh();
  };

  return (
    <div style={{
      display: "flex", justifyContent: "center", alignItems: "center",
      minHeight: "100vh", margin: 0,
      background: "linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    }}>
      <form onSubmit={submit} style={{
        background: "rgba(255,255,255,0.05)", padding: "48px 40px",
        borderRadius: "16px", textAlign: "center", minWidth: "300px",
        backdropFilter: "blur(10px)", border: "1px solid rgba(255,255,255,0.1)",
      }}>
        <div style={{ fontSize: "48px", marginBottom: "8px" }}>🔒</div>
        <h1 style={{ color: "#eee", fontSize: "22px", margin: "0 0 6px" }}>BDSM 夏令营</h1>
        <p style={{ color: "#888", fontSize: "14px", margin: "0 0 28px" }}>请输入密码进入</p >
        <input
          type="password"
          value={password}
          onChange={(e) => { setPassword(e.target.value); setError(""); }}
          placeholder="密码"
          autoFocus
          style={{
            width: "100%", padding: "12px 16px", fontSize: "16px",
            borderRadius: "8px", border: "1px solid rgba(255,255,255,0.15)",
            background: "rgba(255,255,255,0.08)", color: "#fff",
            outline: "none", boxSizing: "border-box", marginBottom: "12px",
          }}
        />
        {error && <p style={{ color: "#e94560", fontSize: "13px", margin: "0 0 12px" }}>{error}</p >}
        <button type="submit" style={{
          width: "100%", padding: "12px", fontSize: "16px", fontWeight: 600,
          borderRadius: "8px", border: "none", cursor: "pointer",
          background: "linear-gradient(135deg, #e94560, #c23152)", color: "#fff",
        }}>进入</button>
      </form>
    </div>
  );
}
