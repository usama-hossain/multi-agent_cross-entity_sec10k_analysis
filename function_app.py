import azure.functions as func

from src.functions import pipeline_blueprints as _pipeline


app = func.FunctionApp()

app.register_functions(_pipeline.kickoff_bp)
app.register_functions(_pipeline.reset_bp)
app.register_functions(_pipeline.worker_bp)
app.register_functions(_pipeline.reconciler_bp)