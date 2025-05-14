pipeline {
    agent any
    environment {
        PYTHONUNBUFFERED = 1
    }
    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        stage('Install Dependencies') {
            steps {
                sh 'pip install -r requirements.txt'
                sh 'playwright install'
            }
        }
        stage('Extract Requirements') {
            steps {
                sh 'python requirement_extractor.py'
            }
        }
        stage('Generate Test Cases') {
            steps {
                sh 'python testcase_generator.py'
            }
        }
        stage('Generate Test Scripts') {
            steps {
                sh 'python script_generator.py'
            }
        }
        stage('Run Playwright Tests') {
            steps {
                sh 'python run_tests.py'
            }
        }
        stage('Self-Heal (Auto-Heal)') {
            steps {
                // 假设只对第一个脚本自愈，可根据实际情况循环所有脚本
                sh 'python auto_heal.py'
            }
        }
        stage('Re-Run Healed Tests') {
            steps {
                // 运行自愈后的脚本（如playwright_test_1.py.healed）
                sh 'pytest playwright_test_1.py.healed --alluredir=allure-results || true'
            }
        }
        stage('Allure Report') {
            steps {
                allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]
            }
        }
    }
    post {
        always {
            archiveArtifacts artifacts: '**/*.healed, **/*.bak, allure-results/**', allowEmptyArchive: true
        }
    }
}