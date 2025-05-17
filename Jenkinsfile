pipeline {
    agent any // 或者指定特定的agent，例如 agent { label 'your-agent-label' }

    environment {
        // Jenkins凭据ID需一致，确保在Jenkins中配置Secret Text类型的凭据，ID为 DEEPSEEK_API_KEY
        // 注意：这里使用 credentials() 方法安全地将凭据注入为环境变量
        DEEPSEEK_API_KEY = credentials('DEEPSEEK_API_KEY')
        // 如果你的API URL不是默认的，也可以在这里配置
        // DEEPSEEK_API_URL = 'https://api.deepseek.com/v1/chat/completions' // 可选
    }

    stages {
        stage('Declarative: Checkout SCM') {
            // 这个stage通常由Jenkinsfile的SCM配置自动处理，这里保留作为示例
            // 如果你的Jenkinsfile是从SCM加载的，这个stage实际上是隐式的
            steps {
                checkout scm
            }
        }

        stage('Checkout') {
            steps {
                script {
                    // 确保当前工作目录正确，这里假设是在agent的工作空间根目录
                    // 如果你的项目在子目录，可能需要 cd 到项目根目录
                    // 例如: dir('your-project-subdirectory') { checkout scm }
                    echo "Checking out code..."
                    checkout scm
                }
            }
        }

        stage('Install Dependencies') {
            steps {
                echo "Installing dependencies from requirements.txt..."
                // 在Windows上使用bat命令
                bat "pip install -r requirements.txt"
                // 安装 Playwright 浏览器二进制文件
                bat "playwright install"
            }
        }

        stage('Generate Test Cases') {
            steps {
                echo "Generating test cases from snapshot..."
                // 确保 page_snapshot.json 文件存在于 Jenkins agent 的工作空间中
                bat "python testcases_generator_by_snapshot.py"
            }
        }

        stage('Generate Scripts') {
            steps {
                echo "Generating Playwright scripts from test cases and snapshot..."
                // 确保 testcases.json 和 page_snapshot.json 文件存在
                // script_generator.py 将读取 testcases.json 并生成脚本到 playwright_scripts 目录
                bat "python script_generator.py"
            }
        }

        stage('Run Tests') {
            steps {
                echo "Running Playwright tests..."
                // 运行 playwright_scripts 目录下的测试，并生成 Allure 报告结果
                // --ignore 参数用于忽略生成的 .error.py 文件，避免 pytest 收集错误
                bat "pytest --alluredir=allure-results --ignore=playwright_scripts/*.error.py"
            }
        }

        stage('Generate Allure Report') {
            steps {
                echo "Generating Allure Report..."
                // 生成 Allure 报告 HTML 文件
                // 确保 allure 命令可用，可能需要在 Jenkins agent 上安装 Allure Commandline
                bat "allure generate --clean allure-results -o allure-report"
            }
        }

        stage('Publish Allure Report') {
            steps {
                echo "Publishing Allure Report..."
                // 发布 Allure 报告，使其在 Jenkins UI 中可见
                // 需要 Jenkins 安装 Allure Report Plugin
                script {
                    // 检查报告目录是否存在，避免因报告未生成而导致插件失败
                    def allureReportDir = 'allure-report'
                    if (fileExists(allureReportDir)) {
                        allure([
                            includeProperties: false,
                            reportBuildPolicy: 'ALWAYS', // ALWAYS, UNSTABLE, FAILURE
                            results: [[path: 'allure-results']] // 指向 allure-results 目录
                        ])
                        echo "Allure Report published."
                    } else {
                        echo "Allure Report directory '${allureReportDir}' not found. Skipping publishing."
                        // 可以根据需要决定是否将此标记为不稳定或失败
                        // currentBuild.result = 'UNSTABLE'
                    }
                }
            }
        }
    }

    post {
        always {
            echo 'Pipeline always block executed.'
            // 可以在这里添加清理工作或其他始终执行的步骤
            // 例如：删除生成的文件以保持工作空间整洁
            // cleanWs() // 清理工作空间，根据需要开启
            script {
               if (currentBuild.result == 'SUCCESS') {
                   echo 'Pipeline finished successfully!'
               } else {
                   echo 'Pipeline failed!'
               }
            }
        }
        // 更多条件化的post actions: success, failure, unstable, changed, fixed, aborted
        failure {
            echo 'Pipeline failed. Checking for auto-heal opportunity...'
            // 可以在失败时触发自愈脚本
            script {
                // 检查是否有失败的测试脚本生成了 .error.py 文件
                def errorFiles = findFiles(glob: 'playwright_scripts/*.error.py')
                if (errorFiles.length > 0) {
                    echo "Found ${errorFiles.length} error files. Attempting auto-heal..."
                    // 运行 auto_heal_trigger.py 脚本
                    // 需要确保 auto_heal_trigger.py 脚本能读取这些错误文件并触发自愈逻辑
                    // 这里的实现取决于你的 auto_heal_trigger.py 逻辑
                    // bat "python auto_heal_trigger.py" // 示例：调用自愈触发脚本
                } else {
                    echo "No error files found. Auto-heal not triggered."
                }
            }
        }
        success {
            echo 'Pipeline finished successfully!'
        }
    }
}