from __future__ import annotations

import html
import json
import re


STYLE = """
:root{color-scheme:light;--red:#e6322f;--ink:#211f1c;--muted:#706a64;--paper:#fffdf8;--bg:#f5f1e8;--line:#ded7ce;--ok:#14804a;--warn:#9a6700}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"PingFang TC","Noto Sans TC",sans-serif;min-height:100vh;padding:calc(28px + env(safe-area-inset-top)) 18px calc(32px + env(safe-area-inset-bottom))}
.card{width:min(100%,460px);margin:0 auto;background:var(--paper);border:1px solid var(--line);border-radius:28px;padding:30px 24px;box-shadow:0 18px 50px #352f2918}.brand{display:flex;align-items:center;gap:16px}.icon{width:72px;height:72px;border-radius:18px}.eyebrow{font-size:13px;color:var(--muted);letter-spacing:.08em}.title{font-size:26px;line-height:1.25;margin:4px 0 0}.lead{font-size:16px;line-height:1.7;color:#49443f;margin:22px 0}.steps{display:grid;gap:12px;margin:22px 0}.step{display:flex;gap:12px;align-items:flex-start}.n{flex:0 0 28px;height:28px;border-radius:50%;background:#f3d6d5;color:#9e201e;display:grid;place-items:center;font-weight:800}.step b{display:block;margin-bottom:2px}.step span{font-size:14px;color:var(--muted);line-height:1.45}.guide{margin:22px 0;padding:18px;border:2px solid #e7b43b;border-radius:16px;background:#fff9e9}.guide h2{font-size:19px;margin:0 0 12px}.guide ol{margin:0;padding-left:22px}.guide li{margin:10px 0;line-height:1.55}.guide .fallback{margin:16px 0 0;padding:13px;border-radius:12px;background:#fff;color:#5e4300;font-size:14px;line-height:1.6}.field{display:grid;gap:7px;margin:18px 0}.field label{font-weight:700}.field input{width:100%;font-size:17px;padding:14px;border:1px solid #bbb1a6;border-radius:12px;background:#fff}.consent{display:flex;gap:10px;align-items:flex-start;font-size:14px;line-height:1.5;color:#4d4843}.consent input{margin-top:3px;width:20px;height:20px}.button{appearance:none;border:0;width:100%;display:block;text-align:center;text-decoration:none;background:var(--red);color:white;border-radius:15px;padding:16px 18px;font-size:18px;font-weight:800;margin-top:20px}.button.secondary{background:#292622}.button.disabled{background:#9a9691;pointer-events:none}.privacy{font-size:12px;color:var(--muted);line-height:1.55;margin-top:18px}.status{padding:14px 16px;border-radius:14px;background:#f2eee8;margin:20px 0;font-size:15px;line-height:1.5}.status.ok{background:#e9f7ef;color:#0d683b}.status.warn{background:#fff4d6;color:#775000}.code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.footer{text-align:center;font-size:12px;color:var(--muted);margin-top:18px}.hidden{display:none}
"""


def style_for(config: dict) -> str:
    accent = str(config.get("brand_color", "#e6322f"))
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", accent):
        accent = "#e6322f"
    return STYLE.replace("--red:#e6322f", f"--red:{accent}")


def shell(config: dict, title: str, body: str, *, script: str = "") -> str:
    footer = f"{html.escape(config['organization'])} · {html.escape(config['app_name'])}"
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="format-detection" content="telephone=no"><title>{html.escape(title)}</title><style>{style_for(config)}</style></head><body>{body}<div class="footer">{footer}</div>{script}</body></html>"""


def landing_page(config: dict, access: str) -> str:
    content = f"""
<main class="card"><div class="brand"><img class="icon" src="/assets/icon-512.png" alt=""><div><div class="eyebrow">IPHONE 安裝服務</div><h1 class="title">{html.escape(config['app_name'])}</h1></div></div>
<p class="lead">請使用要安裝 App 的 iPhone Safari 開啟本頁。系統會先登記裝置，完成後直接顯示安裝按鈕。</p>
<form method="post" action="/start"><input type="hidden" name="access" value="{html.escape(access, quote=True)}"><button class="button" type="submit">開始 iPhone 安裝</button></form>
<div class="privacy">裝置登記需由使用者明確同意。系統僅取得 UDID、產品型號與 iOS 版本，不包含照片、聯絡人、密碼或定位。</div></main>"""
    return shell(config, config["app_name"], content)


def line_browser_page(config: dict, request_target: str = "/") -> str:
    safe_target = request_target if request_target.startswith("/") else "/"
    https_url = config["base_url"].rstrip("/") + safe_target
    safari_url = "x-safari-" + https_url
    content = f"""
<main class="card"><div class="brand"><img class="icon" src="/assets/icon-512.png" alt=""><div><div class="eyebrow">需要使用 SAFARI</div><h1 class="title">請改用 Safari 繼續</h1></div></div>
<div class="status warn"><b>LINE 內建瀏覽器不支援 iPhone 描述檔安裝。</b><br>此頁已停止安裝流程；切換到 Safari 後才會顯示裝置登記與 App 安裝按鈕。</div>
<a id="open-safari" class="button" href="{html.escape(safari_url, quote=True)}">立即改用 Safari 開啟</a>
<section class="guide" aria-labelledby="line-guide"><h2 id="line-guide">如果上方按鈕沒有反應</h2><ol><li>在 LINE 目前頁面點右下角或右上角的 <b>「⋯」</b>。</li><li>選擇 <b>「使用預設瀏覽器開啟」</b>、<b>「在 Safari 中開啟」</b>或「用其他應用程式開啟」。</li><li>確認 Safari 網址列顯示 <b>{html.escape(config["base_url"].split("//", 1)[-1])}</b>，再開始 iPhone 安裝。</li></ol><div class="fallback"><b>仍找不到選項？</b><br>點下方「複製安裝網址」，再手動打開 Safari，貼到網址列後前往。</div></section>
<button id="copy-url" class="button secondary" type="button">複製安裝網址</button>
<div id="copy-result" class="privacy" role="status" aria-live="polite"></div></main>"""
    script = f"""<script>
const installUrl={json.dumps(https_url)};
document.getElementById('copy-url').addEventListener('click',async()=>{{
  const result=document.getElementById('copy-result');
  try{{await navigator.clipboard.writeText(installUrl);result.textContent='已複製。現在請打開 Safari，貼到網址列。'}}
  catch(e){{result.textContent='請長按複製這個網址： '+installUrl;}}
}});
</script>"""
    return shell(config, "請改用 Safari", content, script=script)


def enrollment_page(config: dict, token: str, record: dict) -> str:
    consented = bool(record.get("consented_at"))
    label = html.escape(record.get("device_label") or "")
    ttl = int(config["token_ttl_minutes"])
    retention = int(config["data_retention_days"])
    if not consented:
        content = f"""
<main class="card"><div class="brand"><img class="icon" src="/assets/icon-512.png" alt=""><div><div class="eyebrow">IOS 裝置登記</div><h1 class="title">{html.escape(config['app_name'])}</h1></div></div>
<p class="lead">安裝正式 iPhone 測試版前，需要先登記這支裝置。整個流程約 1 分鐘。</p>
<div class="steps"><div class="step"><div class="n">1</div><div><b>下載登記描述檔</b><span>描述檔只要求 UDID、機型與系統版本。</span></div></div><div class="step"><div class="n">2</div><div><b>在「設定」完成安裝</b><span>iPhone 會先顯示資料內容，確認後才送出。</span></div></div><div class="step"><div class="n">3</div><div><b>回到本頁安裝 App</b><span>裝置完成簽章後，頁面會出現安裝按鈕。</span></div></div></div>
<form method="post" action="/e/{token}/consent"><div class="field"><label for="device_label">客戶或裝置名稱</label><input id="device_label" name="device_label" maxlength="80" autocomplete="name" placeholder="例如：王先生的 iPhone" value="{label}"></div><label class="consent"><input type="checkbox" name="consent" value="yes" required><span>我同意將本裝置的 UDID、產品型號與 iOS 版本傳送給 {html.escape(config['organization'])}，僅供建立 Apple Ad Hoc 安裝資格；資料保存最多 {retention} 天。</span></label><button class="button" type="submit">同意並開始</button></form>
<div class="privacy">一次性連結有效 {ttl} 分鐘。系統不會取得照片、聯絡人、密碼、定位、IMEI 或 SIM 卡資料。</div></main>"""
        return shell(config, config["service_name"], content)

    status = record.get("status", "consented")
    status_copy = {
        "consented": ("下一步：下載描述檔", "點下方按鈕後，Safari 詢問是否允許下載時請點「允許」。", ""),
        "profile_downloaded": ("描述檔已下載", "請依照下方黃色區塊的完整路徑，在 iPhone「設定」完成描述檔安裝。", "warn"),
        "collected": ("已取得裝置資料", "正在建立這支 iPhone 的安裝資格，頁面會自動更新。", "warn"),
        "registering": ("正在登記 Apple 裝置", "通常數分鐘內完成，請保持本頁開啟。", "warn"),
        "exporting": ("正在產生安裝檔", f"裝置已登記，正在重新簽署 {html.escape(config['app_short_name'])} App。", "warn"),
        "ready": ("可以安裝了", f"下方「安裝 {html.escape(config['app_short_name'])}」只要點一次；送出後請回到 iPhone 主畫面檢查。", "ok"),
        "error": ("處理需要重試", html.escape(record.get("public_error") or "請稍後重新整理本頁。"), "warn"),
    }
    heading, description, klass = status_copy.get(status, status_copy["collected"])
    ready = status == "ready"
    app_short = html.escape(config["app_short_name"])
    controls = (f'<a id="install-app" class="button" href="itms-services://?action=download-manifest&amp;url={html.escape(config["base_url"] + "/manifest.plist")}">安裝 {app_short}（只需點一次）</a><div id="install-sent" class="status ok hidden"><b>已開始下載，請回到手機主畫面</b><br>請查看「{app_short}」圖示是否已開始下載。下載可能需要 1～2 分鐘，請勿重複點擊安裝。安裝完成後，請依照下方教學開啟「開發者模式」。</div>' if ready else f'<a class="button secondary" href="/e/{token}/profile.mobileconfig">下載裝置登記描述檔</a>')
    if status in {"collected", "registering", "exporting"}:
        controls = '<button class="button disabled" type="button">處理中，請稍候</button>'
    if ready:
        instructions = f"""<section id="developer-mode-guide" class="guide hidden" aria-labelledby="developer-mode-title"><h2 id="developer-mode-title">安裝後：開啟「開發者模式」</h2><div class="status warn"><b>Apple 要求手動安裝的 IPA App 必須先開啟開發者模式，才能正常打開。</b></div><ol><li>先回到主畫面，等待「{app_short}」下載完成，接著<b>點開 App 一次</b>。</li><li>打開 iPhone <b>「設定」→「隱私權與安全性」</b>。</li><li>往下滑到「安全性」區域，點 <b>「開發者模式」</b>，開啟右側開關。</li><li>在警告視窗點 <b>「重新啟動」</b>。</li><li>iPhone 重新開機並解鎖後，在確認視窗點 <b>「開啟」／「Enable」</b>，再輸入手機解鎖密碼。</li><li>回到主畫面，重新打開「{app_short}」。</li></ol><div class="fallback"><b>設定裡看不到「開發者模式」？</b><br>先確認 App 已安裝完成並嘗試打開一次。若仍沒有此選項，需要先用傳輸線把 iPhone 連到 Mac、在手機點「信任」，並開啟 Xcode 的 <b>Window → Devices and Simulators</b> 完成一次配對；再回到「設定 → 隱私權與安全性」查看。<br><br><a href="https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device" target="_blank" rel="noopener">查看 Apple 官方開啟方式</a></div></section>"""
    else:
        instructions = f"""<section class="guide" aria-labelledby="settings-guide"><h2 id="settings-guide">下載後，請照這條路徑操作</h2><ol><li>Safari 跳出「此網站正嘗試下載設定描述檔」時，點 <b>「允許」</b>，看到「描述檔已下載」後點「關閉」。</li><li>離開 Safari，打開 iPhone 灰色齒輪圖示的 <b>「設定」App</b>。</li><li>在設定首頁、Apple 帳號姓名的下方，點 <b>「已下載描述檔」</b>。</li><li>進入「{html.escape(config['service_name'])}」後，點右上角 <b>「安裝」</b>，輸入手機解鎖密碼，再點一次「安裝」。</li><li>看到安裝完成後點 <b>「完成」</b>。系統通常會自動回到本頁；若沒有，請自行打開 Safari，回到剛才的頁面。</li></ol><div class="fallback"><b>設定首頁沒看到「已下載描述檔」？</b><br>請改走：<b>設定 → 一般 → VPN 與裝置管理</b>（舊版 iOS 可能顯示「描述檔與裝置管理」）→「{html.escape(config['service_name'])}」→右上角「安裝」。<br><br>在「VPN 與裝置管理」也找不到時，回到 Safari 再按一次「下載裝置登記描述檔」，並確認有點到「允許」。</div></section>"""
    content = f"""
<main class="card"><div class="brand"><img class="icon" src="/assets/icon-512.png" alt=""><div><div class="eyebrow">IOS 裝置登記</div><h1 class="title">{html.escape(config['app_name'])}</h1></div></div>
<div id="status" class="status {klass}"><b>{heading}</b><br>{description}</div>{controls}
{instructions}
<div class="privacy">完成 App 安裝後，可在「設定」→「一般」→「VPN 與裝置管理」移除「{html.escape(config['service_name'])}」。</div></main>"""
    page_script = ""
    if ready:
        page_script = f"""<script>
const installButton=document.getElementById('install-app');
const installNotice=document.getElementById('install-sent');
const developerModeGuide=document.getElementById('developer-mode-guide');
const installStateKey={json.dumps('ios-install-clicked:' + config['bundle_id'] + ':' + token + ':' + str(config['bundle_version']))};
function markInstallSent(){{
  installButton.classList.add('disabled');
  installButton.setAttribute('aria-disabled','true');
  installButton.removeAttribute('href');
  installButton.textContent='已開始下載，請回到手機主畫面';
  installNotice.classList.remove('hidden');
  developerModeGuide.classList.remove('hidden');
}}
try{{if(localStorage.getItem(installStateKey)==='1')markInstallSent();}}catch(e){{}}
installButton.addEventListener('click',event=>{{
  if(installButton.getAttribute('aria-disabled')==='true'){{event.preventDefault();return;}}
  const destination=installButton.href;
  event.preventDefault();
  try{{localStorage.setItem(installStateKey,'1');}}catch(e){{}}
  markInstallSent();
  window.location.href=destination;
}});
</script>"""
    else:
        page_script = f"""<script>const current={json.dumps(status)};setInterval(async()=>{{try{{const r=await fetch('/e/{token}/status',{{cache:'no-store'}});const j=await r.json();if(j.status!==current)location.reload()}}catch(e){{}}}},4000);</script>"""
    return shell(config, config["service_name"], content, script=page_script)


def error_page(config: dict, message: str) -> str:
    content = f'<main class="card"><h1 class="title">連結狀態</h1><div class="status warn">{html.escape(message)}</div><div class="privacy">請重新開啟您收到的完整安裝連結；完整網址包含授權碼。</div></main>'
    return shell(config, config["service_name"], content)


def profile_plist(config: dict, token: str, payload_uuid: str) -> bytes:
    callback = f"{config['base_url']}/profile/{token}"
    text = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>PayloadContent</key><dict>
<key>URL</key><string>{html.escape(callback)}</string>
<key>DeviceAttributes</key><array><string>UDID</string><string>PRODUCT</string><string>VERSION</string></array>
<key>Challenge</key><string>{token}</string>
</dict>
<key>PayloadOrganization</key><string>{html.escape(config['organization'])}</string>
<key>PayloadDisplayName</key><string>{html.escape(config['service_name'])}</string>
<key>PayloadVersion</key><integer>1</integer>
<key>PayloadUUID</key><string>{payload_uuid}</string>
<key>PayloadIdentifier</key><string>{config['profile_identifier_prefix']}.{token}</string>
<key>PayloadDescription</key><string>取得本裝置的 UDID、產品型號與 iOS 版本，以建立 {html.escape(config['app_name'])} Ad Hoc 安裝資格。不包含照片、聯絡人、密碼、定位、IMEI 或 SIM 卡資料。</string>
<key>PayloadType</key><string>Profile Service</string>
</dict></plist>"""
    return text.encode("utf-8")


def manifest_plist(config: dict) -> bytes:
    base = config["base_url"]
    text = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>items</key><array><dict><key>assets</key><array>
<dict><key>kind</key><string>software-package</string><key>url</key><string>{base}/downloads/{config["app_ipa_filename"]}</string></dict>
<dict><key>kind</key><string>display-image</string><key>url</key><string>{base}/assets/icon-57.png</string></dict>
<dict><key>kind</key><string>full-size-image</string><key>url</key><string>{base}/assets/icon-512.png</string></dict>
</array><key>metadata</key><dict><key>bundle-identifier</key><string>{config['bundle_id']}</string><key>bundle-version</key><string>{config['bundle_version']}</string><key>kind</key><string>software</string><key>title</key><string>{config['app_short_name']}</string></dict></dict></array></dict></plist>"""
    return text.encode("utf-8")
