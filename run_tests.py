"""
运行自动化测试脚本模块
使用pytest运行所有playwright_test_*.py脚本，并生成Allure报告
"""

import os
import subprocess
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def run_pytest_tests(test_pattern="playwright_scripts/test_playwright_*.py", allure_dir="allure-results"):
    """
    使用pytest运行指定模式的测试文件，并生成Allure报告。
    """
    logging.info(f"正在运行测试脚本: {test_pattern}")
    logging.info(f"Allure报告将生成到目录: {allure_dir}")

    # 确保Allure报告目录存在
    if not os.path.exists(allure_dir):
        os.makedirs(allure_dir)
        logging.info(f"已创建Allure报告目录: {allure_dir}")

    # 构建pytest命令
    # --clean-alluredir 运行前清空报告目录 (可选，根据需要决定是否清空)
    # --alluredir 指定报告输出目录
    command = ["pytest", test_pattern, f"--alluredir={allure_dir}"]

    logging.info(f"执行命令: {' '.join(command)}")

    try:
        # 运行命令并捕获输出
        # text=True, encoding='utf-8'确保输出正确解码
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', check=False) # check=False 即使pytest失败也不抛异常

        logging.info("Pytest 执行完成。")
        logging.info("--- Pytest 标准输出 ---")
        logging.info(result.stdout)
        logging.info("--- Pytest 标准错误 ---")
        logging.info(result.stderr)
        logging.info("--- Pytest 执行结束 ---")

        # 根据pytest的退出码判断测试是否失败
        if result.returncode != 0:
            logging.error(f"Pytest 执行失败，退出码: {result.returncode}")
            # 将pytest的错误输出写入文件，便于后续自愈分析
            with open("pytest_errors.log", "w", encoding="utf-8") as f:
                f.write(result.stdout)
                f.write(result.stderr)
            return False # 表示测试失败
        else:
            logging.info("Pytest 执行成功，所有测试通过或被跳过。")
            # 如果没有失败，清理可能的错误日志文件
            if os.path.exists("pytest_errors.log"):
                 os.remove("pytest_errors.log")
            return True # 表示测试成功

    except FileNotFoundError:
        logging.error("未找到 pytest 命令。请确保 pytest 已安装并可在当前环境中访问。")
        # 写入一个错误标记文件，通知自愈脚本
        with open("pytest_errors.log", "w", encoding="utf-8") as f:
            f.write("未找到 pytest 命令")
        return False
    except Exception as e:
        logging.error(f"运行 pytest 时发生异常: {e}")
        with open("pytest_errors.log", "w", encoding="utf-8") as f:
            f.write(f"运行 pytest 时发生异常: {e}")
        return False


if __name__ == "__main__":
    # 运行所有以 playwright_test_ 开头，.py 结尾的脚本
    success = run_pytest_tests()

    # 如果测试失败，通知Jenkins流程失败 (Jenkinsfile中的 || exit 0 可以处理)
    if not success:
        exit(1) # 通知Jenkins该阶段失败