"""
页面快照收集器模块
负责使用 Playwright 访问指定 URL，收集页面上关键的 UI 元素信息，
并将其保存为 JSON 文件供后续测试用例生成和脚本生成使用。
"""
import os
import json
from playwright.sync_api import sync_playwright
from loguru import logger

# 配置日志
logger.add("file_{time}.log", rotation="1 day", level="INFO")

def collect_snapshots(urls, output_dir="."):
    """
    访问指定的 URLs，收集页面快照（UI元素信息），并保存到指定目录。

    Args:
        urls (list): 需要访问的 URL 列表。
        output_dir (str): 快照文件保存的目录。默认为当前目录。
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logger.info(f"创建快照输出目录: {output_dir}")

    snapshot_file_path = os.path.join(output_dir, "page_snapshot.json") # 指定输出文件名为 page_snapshot.json
    all_snapshots_data = {} # 存储所有URL的快照数据

    with sync_playwright() as p:
        # 使用 Chromium 浏览器，并设置适当的超时
        browser = p.chromium.launch(timeout=60000) # 增加浏览器启动超时
        context = browser.new_context()
        page = context.new_page()

        for url in urls:
            try:
                logger.info(f"正在访问页面: {url}")
                page.goto(url, timeout=60000) # 增加页面跳转超时
                # 更改等待状态为 "load"，通常比 "networkidle" 更可靠
                page.wait_for_load_state("load", timeout=60000) # 增加等待加载超时

                # --- 登录逻辑示例 (如果需要，请替换为实际登录步骤) ---
                # 假设第一个URL是登录页，并且只需要收集登录后的页面快照
                if "login" in url.lower(): # 示例：如果URL包含"login"
                    logger.info("Performing login...")
                    try:
                        # 假设用户名和密码输入框以及登录按钮有特定的选择器
                        # 请替换为实际的选择器
                        username_field = page.locator('input[name="username"]')
                        password_field = page.locator('input[name="password"]')
                        login_button = page.locator('button[type="submit"]') # 或其他登录按钮选择器

                        # 确保点击后填写 (用户需求)
                        if username_field.count() > 0:
                            username_field.click(timeout=10000) # 增加点击超时
                            username_field.fill("your_username", timeout=10000) # 替换为实际用户名，增加填写超时
                        else:
                            logger.warning("未找到用户名输入框")

                        if password_field.count() > 0:
                             password_field.click(timeout=10000) # 增加点击超时
                             password_field.fill("your_password", timeout=10000) # 替换为实际密码，增加填写超时
                        else:
                            logger.warning("未找到密码输入框")

                        if login_button.count() > 0:
                             login_button.click(timeout=30000) # 增加登录按钮点击超时
                             # 等待登录后的页面加载，替换为实际的登录成功后的URL或元素
                             page.wait_for_url("**/dashboard", timeout=60000) # 替换为实际的登录成功后URL
                             logger.info("Login successful.")
                        else:
                            logger.warning("未找到登录按钮")

                    except Exception as e:
                        logger.error(f"登录过程中发生错误: {e}")
                        # 如果登录失败，可以选择跳过当前URL或处理

                # --- 结束登录逻辑示例 ---

                # 捕获特定的 UI 元素作为快照数据
                # 查找所有输入字段、按钮、链接、下拉框和文本域等交互元素
                # 您可以根据实际应用的需求调整这里的选择器
                elements_to_capture_selectors = 'input, button, a, select, textarea, [role="button"], [onclick]' # 添加更多可能代表交互元素的CSS选择器
                elements_to_capture = page.locator(elements_to_capture_selectors)
                current_page_elements = []
                all_elements = elements_to_capture.all()

                logger.info(f"正在收集页面 {url} 的 UI 元素...")
                for i, element in enumerate(all_elements):
                     try:
                         # 尝试获取元素的可见文本或value
                         text_content = element.text_content().strip() if element.text_content() else ""
                         if not text_content and 'value' in element.evaluate('el => el.attributes').keys():
                             text_content = element.get_attribute('value') or ""

                         # 尝试获取元素的名称、ID、类型、角色等属性
                         name = element.get_attribute('name')
                         id_attr = element.get_attribute('id')
                         type_attr = element.get_attribute('type')
                         role_attr = element.get_attribute('role')
                         # 获取元素的标签名
                         tag_name = element.evaluate('el => el.tagName')

                         # 仅捕获可见元素
                         if element.is_visible():
                             element_info = {
                                 "tag": tag_name,
                                 "selector": f"css={elements_to_capture_selectors} >> nth={i}", # 使用 nth 伪类作为示例选择器
                                 "text": text_content,
                                 "name": name,
                                 "id": id_attr,
                                 "type": type_attr,
                                 "role": role_attr,
                                 # 可以添加其他您认为重要的属性，例如 class, href (for links), etc.
                                 # "class": element.get_attribute('class'),
                                 # "href": element.get_attribute('href'),
                             }
                             current_page_elements.append(element_info)
                             # logger.debug(f"Captured element: {element_info}") # 调试信息

                     except Exception as e:
                         logger.warning(f"收集页面 {url} 第 {i} 个元素时发生错误: {e}")
                         continue # 继续收集下一个元素

                all_snapshots_data[url] = current_page_elements
                logger.info(f"页面 {url} 的 UI 元素收集完成，共收集 {len(current_page_elements)} 个元素。")


            except Exception as e:
                logger.error(f"访问或处理页面 {url} 时发生错误: {e}")
                # 如果某个URL处理失败，记录错误并继续处理下一个URL

        # 将收集到的所有快照数据保存到 JSON 文件
        try:
            with open(snapshot_file_path, 'w', encoding='utf-8') as f:
                json.dump(all_snapshots_data, f, indent=4, ensure_ascii=False)
            logger.info(f"所有页面快照数据已保存到: {snapshot_file_path}")
        except Exception as e:
            logger.error(f"保存快照文件 {snapshot_file_path} 时发生错误: {e}")


        browser.close()
        logger.info("浏览器关闭。")

if __name__ == "__main__":
    # 示例使用，替换为您的目标应用URL
    target_urls = ["http://10.0.62.222:30050/login"] # 替换为实际需要收集快照的URL列表
    output_directory = "snapshots" # 快照文件保存的目录

    logger.info(f"开始收集页面快照到目录: {output_directory}")
    collect_snapshots(target_urls, output_directory)
    logger.info("页面快照收集完成。")