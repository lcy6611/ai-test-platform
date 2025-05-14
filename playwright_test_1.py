from playwright.sync_api import sync_playwright
import traceback
from auto_heal_trigger import trigger_auto_heal  # 如有自愈触发需求

def test_login_form_fields():
    """验证登录表单的输入字段"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        try:
            """1. 打开登录页面"""
            page.goto("http://10.0.62.222:30050/")
            page.wait_for_load_state("load", timeout=60000)
            # ... 其它测试步骤 ...
            assert False, "模拟断言失败"  # 测试用，实际可删除
        except Exception as e:
            error_message = traceback.format_exc()
            # 标准写法：异常写入日志
            log_path = __file__.replace(".py", ".log")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(error_message)
            print("检测到异常，已写入日志。")
            # 可选：自动触发自愈
            # healed_path = trigger_auto_heal(__file__, error_message, "http://10.0.62.222:30050/")
            # if healed_path:
            #     print(f"你可以手动或自动运行自愈脚本: {healed_path}")
            raise
        finally:
            context.close()
            browser.close()

if __name__ == "__main__":
    test_login_form_fields()