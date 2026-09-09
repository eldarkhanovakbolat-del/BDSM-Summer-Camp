import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") || requestHeaders.get("host") || "127.0.0.1:3000";
  const protocol = requestHeaders.get("x-forwarded-proto") || (host.startsWith("127.0.0.1") ? "http" : "https");
  const base = new URL(`${protocol}://${host}`);
  return {
    metadataBase: base,
    title: "BDSM 夏令营",
    description: "从 BDSM Wiki 选择课程，与 AI 一起学习和进行纯文字体验。",
    openGraph: {
      title: "BDSM 夏令营",
      description: "从理解开始，一起学习与体验。",
      images: [{ url: "/og.png", width: 1774, height: 887, alt: "BDSM 夏令营" }],
    },
    twitter: {
      card: "summary_large_image",
      title: "BDSM 夏令营",
      description: "从理解开始，一起学习与体验。",
      images: ["/og.png"],
    },
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <div id="auth-gate" style={{
          position: "fixed", inset: 0, zIndex: 99999,
          background: "linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)",
          display: "flex", justifyContent: "center", alignItems: "center",
          fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        }}>
          <div style={{
            background: "rgba(255,255,255,0.05)", padding: "48px 40px",
            borderRadius: "16px", textAlign: "center", minWidth: "300px",
            border: "1px solid rgba(255,255,255,0.1)",
          }}>
            <div style={{ fontSize: "48px", marginBottom: "8px" }}>🔒</div>
            <h1 style={{ color: "#eee", fontSize: "22px", margin: "0 0 6px" }}>BDSM 夏令营</h1>
            <p style={{ color: "#888", fontSize: "14px", margin: "0 0 28px" }}>请输入密码进入</p >
            <form id="auth-form">
              <input id="auth-input" type="password" placeholder="密码" autoFocus
                style={{
                  width: "100%", padding: "12px 16px", fontSize: "16px",
                  borderRadius: "8px", border: "1px solid rgba(255,255,255,0.15)",
                  background: "rgba(255,255,255,0.08)", color: "#fff",
                  outline: "none", boxSizing: "border-box", marginBottom: "12px",
                }} />
              <p id="auth-error" style={{ color: "#e94560", fontSize: "13px", margin: "0 0 12px", display: "none" }}>密码错误</p >
              <button type="submit" style={{
                width: "100%", padding: "12px", fontSize: "16px", fontWeight: 600,
                borderRadius: "8px", border: "none", cursor: "pointer",
                background: "linear-gradient(135deg, #e94560, #c23152)", color: "#fff",
              }}>进入</button>
            </form>
          </div>
        </div>
        <div id="site-content" style={{ display: "none" }}>{children}</div>
        <script dangerouslySetInnerHTML={{ __html: `
          (function(){
            var PASSWORD = "303607";
            function getCookie(name){
              var m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
              return m ? decodeURIComponent(m[1]) : null;
            }
            if(getCookie("bdsm_auth") === PASSWORD){
              document.getElementById("auth-gate").style.display = "none";
              document.getElementById("site-content").style.display = "";
              return;
            }
            document.getElementById("auth-form").addEventListener("submit", function(e){
              e.preventDefault();
              var val = document.getElementById("auth-input").value;
              if(val === PASSWORD){
                document.cookie = "bdsm_auth=" + encodeURIComponent(val) + "; path=/; max-age=31536000; SameSite=Lax";
                location.reload();
              } else {
                document.getElementById("auth-error").style.display = "block";
                document.getElementById("auth-input").value = "";
                document.getElementById("auth-input").focus();
              }
            });
          })();
        `}} />
      </body>
    </html>
  );
}
