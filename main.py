import time
import urllib.request, json
from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
    
# True=无头模式（后台运行），False=显示浏览器窗口
HEADLESS  = True
SLOW_MO   = 100

# 获取明天日期，格式 YYYY-MM-DD
DATE = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
with open('data.json', 'r', encoding='utf-8') as f:
    data = json.load(f) 

USERNAME = data["name"]
PASSWORD = data["password"]
SEATS    = data["seats"]
ROOM     = SEATS[0]
WEBHOOK  = data["webhook"]

URL_INDEX = "https://libic.zcmu.edu.cn/h5/index.html"
URL_APP   = f"https://libic.zcmu.edu.cn/h5/index.html#/SeatScreening/1/seatSelect?date={DATE}&area={ROOM}"

def debug_snapshot(page, info):
    path = f"{info}.png"
    page.screenshot(path=path)
    print(f"截图已保存为 {info}.png")
    
def debug_html(page):
    html_content = page.content()
    print(html_content)  

def reserve():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            slow_mo=SLOW_MO,
            args=[
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--disable-web-security',      # 某些 CORS 问题
                '--disable-features=IsolateOrigins,site-per-process',
                '--window-size=1280,800',
            ]
        )
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        # ---------- 注入反检测脚本（手动增强）----------
        page.add_init_script("""
            // 覆盖 webdriver
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            // 伪造 chrome 对象
            window.chrome = { runtime: {} };
            // 伪造 plugins
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            // 伪造 languages
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh']});
            // 伪造 permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
            // 去除 headless 痕迹
            Object.defineProperty(navigator, 'headless', {get: () => false});
            // 覆盖 userAgent 在 JS 中的读取
            Object.defineProperty(navigator, 'userAgent', {get: () => 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'});
        """)

        # 监听网络请求，打印预约请求（调试用）
        def log_request(request):
            if "/api/Seat/confirm" in request.url:
                print(f"[REQUEST] {request.method} {request.url}")
                print(f"Body: {request.post_data}")
        page.on("request", log_request)

        try:
            print("打开页面")
            page.goto(URL_INDEX)
            page.wait_for_load_state("networkidle")

            if page.is_visible("#username", timeout=3000):
                print("填写登录信息", end="--")
                page.fill("#username", USERNAME)
                page.fill("#password", PASSWORD)
                if page.locator('input[value="LOGIN"]').count() > 0:
                    page.click('input[value="LOGIN"]')
                else:
                    page.click('input[value="登录"]')
                print("登录完成")
            else:
                print("未检测到登录表单, 可能已经登录或需手动处理CAS认证")
        
            print("开始预约", end="--")
            selector = "div.item.btn:has-text('座位预约')"
            page.wait_for_selector(selector, state="visible", timeout=10000)
            page.click(selector)

            print("选择教室", end="--")
            selector = "button.van-button--primary:has-text('预约')"
            page.wait_for_selector("button.van-button--primary:has-text('预约')", timeout=10000)
            page.goto(URL_APP)
            page.goto(URL_APP)

            print("选择日期", end="--")
            print(DATE)
            page.goto(URL_APP)

            print("列表模式", end="--")
            selector = "div.reg-pavilion:has-text('列表模式')"
            page.wait_for_selector(selector, state="visible", timeout=10000)
            page.click(selector)
            page.click(selector)

            print("选择座位", end="--")
            selected_seat = None
            for seat in SEATS[1:]:
                locator = page.locator(".grid-seat .btn").filter(has_text=seat)
                if locator.count() > 0:
                    locator.first.click(force=True)
                    print(f"已选择座位 {seat}")
                    selected_seat = seat
                    break
            if selected_seat is None:
                raise Exception("所有备用座位均不可用")
            
            print("提交预约", end="--")
            selector = "button.van-button--primary.confirm.btn"
            page.wait_for_selector(selector, state="visible", timeout=10000)
            page.click(selector)

            page.wait_for_selector(".block_header:has-text('预约成功')", timeout=15000)
            print("预约成功！")

            message = f":seat | {selected_seat}"
            req = urllib.request.Request(WEBHOOK, data=json.dumps({"msgtype":"text","text":{"content": message}}).encode(), headers={"Content-Type":"application/json"})
            urllib.request.urlopen(req).read()
        except Exception as e:
            print("未检测到预约成功标识，可能预约失败")
            debug_snapshot(page, "reservation_failed")
            message = f":seat | failed"
            req = urllib.request.Request(WEBHOOK, data=json.dumps({"msgtype":"text","text":{"content": message}}).encode(), headers={"Content-Type":"application/json"})
            urllib.request.urlopen(req).read()

        browser.close()

if __name__ == "__main__":
    reserve()