pipeline {
    agent any

    environment {
        // Define environment variables like API keys here
        // DEEPSEEK_API_KEY is defined as a Secret Text credential in Jenkins
        DEEPSEEK_API_KEY = credentials('DEEPSEEK_API_KEY')
    }

    stages {
        stage('Checkout SCM') {
            steps {
                echo 'Checking out code...'
                script {
                     checkout scm
                }
            }
        }
        stage('Install Dependencies') {
            steps {
                echo 'Installing dependencies from requirements.txt...'
                bat 'pip install -r requirements.txt'
                // Install Playwright browsers. Use -m for consistent execution.
                bat 'python -m playwright install'
            }
        }
        stage('Collect Page Snapshot') { // Added stage for collecting snapshot
            steps {
                echo 'Collecting page snapshot...'
                bat 'python page_snapshot_collector.py'
            }
        }
        stage('Generate Test Cases') {
            steps {
                echo 'Gener ating test cases from snapshot...'
                bat 'python testcases_generator_by_snapshot.py'
            }
        }
        stage('Generate Scripts') {
            steps {
                echo 'Generating scripts from test cases...'
                bat 'python script_generator.py'
            }
        }
        stage('Run Tests') {
            steps {
                echo 'Running tests...'
                // The exit code from pytest should be handled in Windows bat to avoid marking the build unstable instead of failed
                // Use || exit /b 1 to ensure failure if pytest exits non-zero
                bat 'pytest --alluredir=allure-results || exit /b 1'
            }
        }
        stage('Generate Allure Report') {
            steps {
                echo 'Generating Allure Report...'
                // Clean previous results and generate report
                bat 'allure generate allure-results --clean'
            }
        }
        stage('Publish Allure Report') {
            steps {
                echo 'Publishing Allure Report...'
                // Configure your Allure Report plugin in Jenkins job settings to pick up 'allure-report' directory
                // Ensure you have the Allure Report plugin installed in Jenkins
                script {
                    publishAllure reportDir: 'allure-report'
                }
            }
        }
    }

    post {
        always {
            echo 'Pipeline always block executed.'
        }
        success {
            echo 'Pipeline finished successfully.'
        }
        failure {
            echo 'Pipeline failed!'
            echo 'Pipeline failed. Checking for auto-heal opportunity...'
            script {
                // Trigger auto-healing process if the build failed
                // This requires auto_heal_trigger.py to be callable, perhaps via a separate script or by adapting it
                // Example (assuming a script trigger_auto_heal.py exists):
                // bat 'python trigger_auto_heal.py'
                // Or integrate the logic directly if possible and appropriate for your setup
                echo "Auto-heal trigger logic goes here if applicable to the Jenkins pipeline level failure."
            }
        }
    }
}