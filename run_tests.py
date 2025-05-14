"""
测试执行编排模块
批量执行Playwright自动化测试脚本并生成Allure报告
"""

import os
import glob

def run_playwright_tests():
    """
    批量执行Playwright自动化测试脚本
    """
    test_files = glob.glob("playwright_test_*.py")
    for test_file in test_files:
        print(f"正在执行: {test_file}")
        os.system(f"pytest {test_file} ")

if __name__ == "__main__":
    run_playwright_tests()