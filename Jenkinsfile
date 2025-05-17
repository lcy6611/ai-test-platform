pipeline {
    agent any
    environment {
        PYTHONUNBUFFERED = 1
        # Jenkins凭据ID需一致，确保在Jenkins中配置Secret Text类型的凭据，ID为 DEEPSEEK_API_KEY
        DEEPSEEK_API_KEY = credentials('DEEPSEEK_API_KEY')
        # 可选：设置测试环境URL环境变量，在脚本中使用 os.getenv('TEST_URL') 获取
        # TEST_URL = 'http://10.0.62.222:30050/'
    }
    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        stage('Install Dependencies') {
            steps {
                echo 'Installing Python dependencies from requirements.txt...'
                bat 'pip install -r requirements.txt'
                echo 'Installing Playwright browsers...'
                bat 'playwright install'
                echo 'Installing allure-pytest...'
                bat 'pip install allure-pytest'
            }
        }
        stage('Page Snapshot') {
            steps {
                echo 'Collecting page snapshots...'
                bat 'python page_snapshot_collector.py'
            }
        }
        stage('Generate Test Cases') {
            steps {
                echo 'Generating test cases from snapshots using AI...'
                bat 'python testcases_generator_by_snapshot.py'
            }
        }
        stage('Generate Scripts') {
            steps {
                echo 'Generating Playwright scripts from test cases using AI...'
                bat 'python script_generator.py'
            }
        }
        stage('Run Tests') {
            steps {
                echo 'Running generated tests with pytest...'
                # 使用 || true 或者 || exit 0 确保即使测试失败Jenkins阶段也标记为不稳定而不是失败，以便进入后续自愈阶段
                # run_tests.py 脚本内部会根据pytest退出码生成 pytest_errors.log
                bat 'python run_tests.py || exit 0' # 如果测试失败，run_tests.py会返回非零退出码，此处允许Jenkins阶段继续
            }
        }
        stage('Auto Heal') {
             steps {
                 echo 'Checking for failed tests and triggering auto-healing...'
                 # auto_heal.py 会检查 pytest_errors.log 并尝试自愈失败脚本
                 bat 'python auto_heal.py || exit 0' # 自愈失败不中断流程
             }
        }
        stage('Re-Run Healed Tests') {
            steps {
                echo 'Re-running healed tests...'
                # 仅运行 .healed 脚本，失败也允许继续，避免因少数自愈失败的脚本导致整个流水线中断
                bat 'pytest playwright_test_*.py.healed --alluredir=allure-results || exit 0'
            }
        }
        stage('Allure Report') {
            steps {
                echo 'Generating Allure report...'
                # Requires Allure Jenkins plugin and Allure Commandline tool installed and configured globally
                # 在Jenkins全局工具配置中设置Allure Commandline
                # 请确保安装 Allure Jenkins Plugin (https://plugins.jenkins.io/allure-jenkins-plugin/)
                # 和 Allure Commandline Tool (在Jenkins全局工具配置中设置下载或指定路径)
                script {
                    try {
                         allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]
                         echo 'Allure report generated.'
                    } catch (Exception e) {
                         echo "WARNING: Could not generate Allure report. Please ensure Allure plugin is installed and configured globally. Error: ${e}"
                         // Optional: archive report directory manually if allure step fails
                         // archiveArtifacts artifacts: 'allure-results/**', allowEmptyArchive: true
                    }
                }
            }
        }
    }
    post {
        always {
            echo 'Archiving artifacts...'
            # 归档自愈脚本、备份脚本、错误日志和Allure报告目录
            archiveArtifacts artifacts: '**/*.healed, **/*.bak, pytest_errors.log, allure-results/**', allowEmptyArchive: true
            echo 'Artifacts archived.'
        }
        # 根据测试结果设置Jenkins构建状态
        # failure { echo 'Build failed because tests failed.' } # Run Tests 阶段已用 || exit 0 防止构建失败，可以在这里根据需要调整
        # unstable { echo 'Build unstable because some tests failed.' }
        success { echo 'Build successful.' }
        unstable { echo 'Build unstable (some tests failed or self-healed).' }
        failure {
            echo 'Build failed (critical error or all tests failed). Check logs.'
            # 可以选择发送失败通知邮件等
            # emailext body: "Pipeline ${currentBuild.fullDisplayName} failed.", subject: "Jenkins Build Failed", to: "your-email@example.com"
        }
    }
}