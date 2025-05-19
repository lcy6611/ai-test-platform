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

def collect_snapshots(urls, output_dir="snapshots"):
    """
    访问指定的 URLs，收集页面快照（UI元素信息），并保存到指定目录。

    Args:
        urls (list): 需要访问的 URL 列表。
        output_dir (str): 快照文件保存的目录。默认为 "snapshots"。
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

                # --- 登录逻辑示例 (请替换为实际登录步骤和选择器) ---
                # 假设第一个URL是登录页，并且只需要收集登录后的页面快照
                if "login" in url.lower(): # 示例：如果URL包含"login"
                    logger.info("Performing login...")

                    # 在尝试登录操作前截取屏幕快照
                    screenshot_path_before_login = os.path.join(output_dir, "login_page_before_action.png")
                    try:
                        page.screenshot(path=screenshot_path_before_login)
                        logger.info(f"登录前页面快照已保存到: {screenshot_path_before_login}")
                    except Exception as e:
                         logger.warning(f"截取登录前快照失败: {e}")


                    try:
                        # !!! IMPORTANT: Replace with actual selectors for your login page !!!
                        # 替换这里的选择器为你找到的准确选择器
                        username_field_selector = '#form_item_username' # <-- 根据您提供的HTML确定的选择器
                        password_field_selector = '#form_item_password' # <-- 根据您提供的HTML确定的选择器
                        login_button_selector = 'text="登 录"'         # <-- 根据您提供的HTML确定的选择器

                        username_field = page.locator(username_field_selector)
                        password_field = page.locator(password_field_selector)
                        login_button = page.locator(login_button_selector)

                        # !!! IMPORTANT: Replace with actual username and password !!!
                        actual_username = "YOUR_USERNAME" # <-- REPLACE THIS with your username
                        actual_password = "YOUR_PASSWORD" # <-- REPLACE THIS with your password

                        logger.info(f"Waiting for username field with selector: {username_field_selector}")
                        try:
                            username_field.wait_for(state='visible', timeout=15000) # 显式等待用户名输入框可见
                            logger.info("Username field is visible.")
                            username_field.click(timeout=10000) # 增加点击超时
                            username_field.fill(actual_username, timeout=10000) # 增加填写超时
                        except Exception as e:
                            logger.warning(f"等待或操作用户名输入框失败，选择器: {username_field_selector}, 错误: {e}")
                            # continue # uncomment to skip if username field cannot be interacted with


                        logger.info(f"Waiting for password field with selector: {password_field_selector}")
                        try:
                            password_field.wait_for(state='visible', timeout=15000) # 显式等待密码输入框可见
                            logger.info("Password field is visible.")
                            password_field.click(timeout=10000) # 增加点击超时
                            password_field.fill(actual_password, timeout=10000) # 增加填写超时
                        except Exception as e:
                            logger.warning(f"等待或操作密码输入框失败，选择器: {password_field_selector}, 错误: {e}")
                            # continue # uncomment to skip if password field cannot be interacted with


                        logger.info(f"Waiting for login button with selector: {login_button_selector}")
                        try:
                            login_button.wait_for(state='visible', timeout=15000) # 显式等待登录按钮可见
                            logger.info("Login button is visible.")
                            login_button.click(timeout=30000) # 增加登录按钮点击超时
                            # !!! IMPORTANT: Replace with the actual URL pattern after successful login !!!
                            # 等待登录后的页面加载，替换为实际的登录成功后的URL或元素
                            # 例如: page.wait_for_url("**/dashboard", timeout=60000)
                            # 或者等待登录后页面的某个特有元素出现: page.wait_for_selector("selector_on_dashboard", timeout=60000)
                            logger.info("Waiting for post-login page...")
                            # 请根据实际登录成功后的页面URL或元素来替换下面的等待逻辑
                            # page.wait_for_url("**/dashboard", timeout=60000) # 示例等待URL
                            # 或者
                            # page.wait_for_selector("div.main-dashboard", timeout=60000) # 示例等待元素

                            # 临时添加一个等待超时作为示例，请用更可靠的等待方法替换
                            page.wait_for_timeout(15000) # 示例：增加等待时间到15秒钟
                            logger.info("Login action performed, proceeded to URL: {}".format(page.url))

                        except Exception as e:
                            logger.warning(f"等待或操作登录按钮失败，选择器: {login_button_selector}, 错误: {e}")
                            # continue # uncomment to skip if login button cannot be interacted with


                    except Exception as e:
                        logger.error(f"登录过程中发生未知错误: {e}")
                        # 如果登录失败，可以选择跳过当前URL或处理
                        continue # 如果登录失败，跳过当前页面的快照收集

                    # 在登录尝试后截取屏幕快照
                    screenshot_path_after_login = os.path.join(output_dir, "login_page_after_action.png")
                    try:
                         page.screenshot(path=screenshot_path_after_login)
                         logger.info(f"登录后页面快照已保存到: {screenshot_path_after_login}")
                    except Exception as e:
                         logger.warning(f"截取登录后快照失败: {e}")

                # --- 结束登录逻辑示例 ---

                # 捕获特定的 UI 元素作为快照数据
                # 查找所有输入字段、按钮、链接、下拉框和文本域等交互元素
                # 您可以根据实际应用的需求调整这里的选择器
                elements_to_capture_selectors = 'input, button, a, select, textarea, [role="button"], [onclick]' # 添加更多可能代表交互元素的CSS选择器
                elements_to_capture = page.locator(elements_to_capture_selectors)
                current_page_elements = []
                # 添加等待，确保元素有时间加载并可见
                try:
                    # 等待至少一个交互元素可见，但如果页面为空，可能会超时
                    elements_to_capture.first.wait_for(state='visible', timeout=15000) # 增加等待时间
                    logger.info("页面上的交互元素已加载并可见。")
                except Exception as e:
                    # 如果等待超时，可能是页面加载问题或没有匹配的元素
                    logger.warning(f"等待页面交互元素超时或失败: {e}. 尝试继续收集可见元素（即使没有匹配的）。")


                all_elements = elements_to_capture.all()

                logger.info(f"正在收集页面 {page.url} 的 UI 元素...") # 记录当前页面的URL
                collected_count = 0
                for i, element in enumerate(all_elements):
                     try:
                         # 仅捕获可见元素
                         if element.is_visible():
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

                             element_info = {
                                 "tag": tag_name,
                                 # 使用 Playwright 的 auto-generating selector 可能是更好的选择，或者构建更稳健的选择器
                                 # 这里的 nth 伪类仅作为示例
                                 # 考虑使用 element.locator('').evaluate() 获取更精确的选择器，但这会增加复杂性
                                 "selector": f"css={elements_to_capture_selectors} >> nth={i}",
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
                             collected_count += 1
                             # logger.debug(f"Captured element: {element_info}") # 调试信息

                     except Exception as e:
                         logger.warning(f"收集页面 {page.url} 第 {i} 个元素时发生错误: {e}")
                         continue # 继续收集下一个元素

                # 使用当前页面的最终 URL 作为键
                all_snapshots_data[page.url] = current_page_elements
                logger.info(f"页面 {page.url} 的 UI 元素收集完成，共收集 {collected_count} 个可见元素。") # 记录实际收集到的可见元素数量


            except Exception as e:
                logger.error(f"访问或处理页面 {url} 时发生错误: {e}")
                # 如果某个URL处理失败，记录错误并继续处理下一个URL
                all_snapshots_data[url] = {"error": str(e)} # 记录错误信息到快照数据中

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
    # 如果需要收集登录后的页面，请将登录页URL放在列表的第一个
    target_urls = ["http://10.0.62.222:30050/login"] # <-- REPLACE WITH YOUR TARGET URL(S)
    output_directory = "snapshots" # 快照文件保存的目录

    logger.info(f"开始收集页面快照到目录: {output_directory}")
    collect_snapshots(target_urls, output_directory)
    logger.info("页面快照收集完成。")