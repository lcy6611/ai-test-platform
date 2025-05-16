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
                bat 'pip install -r requirements.txt'
                bat 'python -m playwright install'
                // allure-pytest 建议直接写在 requirements.txt 里，无需单独安装
            }
        }
        stage('Page Snapshot') {
            steps {
                bat 'python page_snapshot_collector.py'
            }
        }
        stage('Generate Test Cases') {
            steps {
                bat 'python testcases_generator_by_snapshot.py'
            }
        }
        stage('Generate Scripts') {
            steps {
                bat 'python script_generator.py'
            }
        }
        stage('Run Tests') {
            steps {
                bat 'python run_tests.py'
            }
        }
        stage('Auto Heal') {
            steps {
                bat 'python auto_heal.py'
            }
        }
        stage('Re-Run Healed Tests') {
            steps {
                // Windows 下忽略 pytest 失败可用如下写法
                bat '''
                pytest playwright_test_*.py.healed --alluredir=allure-results
                exit 0
                '''
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