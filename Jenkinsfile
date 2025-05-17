pipeline {
    agent any // 或者指定具体的 Windows 节点

    environment {
        // 从 Jenkins 凭据中注入 Secret Text 类型的 DEEPSEEK_API_KEY
        // 确保在 Jenkins 中创建了一个 Secret Text 凭据，ID 必须是 DEEPSEEK_API_KEY
        DEEPSEEK_API_KEY = credentials('DEEPSEEK_API_KEY')
    }

    stages {
        stage('Checkout') {
            steps {
                // 假设您的代码仓库是 git，并且已经配置在 Jenkins Pipeline 的 SCM 中
                // 如果没有配置，需要在这里添加 checkout scm
                 checkout scm
            }
        }

        stage('Install Dependencies') {
            steps {
                // 在 Windows 环境下使用 bat 命令
                bat 'pip install -r requirements.txt'
            }
        }

        stage('Generate Test Cases') {
            steps {
                // 在 Windows 环境下使用 bat 命令运行 Python 脚本
                // DEEPSEEK_API_KEY 环境变量会自动注入到这个阶段
                bat 'python testcases_generator_by_snapshot.py'
            }
        }

        stage('Generate Scripts') {
            steps {
                // 在 Windows 环境下使用 bat 命令运行 Python 脚本
                bat 'python script_generator.py'
            }
        }

        stage('Run Tests') {
            steps {
                // 在 Windows 环境下使用 bat 命令运行 pytest
                // --alluredir=allure-results 参数用于生成 Allure 报告数据
                bat 'pytest --alluredir=allure-results'
            }
        }

        stage('Generate Allure Report') {
            steps {
                // 生成 Allure 报告
                // 确保 Jenkins 环境已经安装并配置了 Allure Commandline Tool
                // 'allure' 命令可能需要配置到系统 PATH 或在 Jenkins 的全局工具配置中设置
                // 如果 'allure' 命令找不到，请检查您的 Jenkins 系统配置
                bat 'allure generate --clean allure-results'
                // 您可能需要一个 post 阶段来发布 Allure 报告，这里只是生成
                // 例如: allure([includeProperties: false, reportBuildFailure: true, reportDir: 'allure-report'])
            }
        }
    }

    post {
        always {
            // 总是执行的清理或其他操作
            // 可以添加 Allure 报告发布的 post 阶段在这里
            // 例如:
            // allure([includeProperties: false, reportBuildFailure: true, reportDir: 'allure-report'])
        }
        success {
            echo 'Pipeline succeeded!'
        }
        failure {
            echo 'Pipeline failed!'
        }
    }
}