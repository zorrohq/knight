from celery import Celery

# boilerplate for reference
app = Celery('main', broker='redis://localhost:6379/0')

@app.task
def fix_issue():
    return 'hello world'
