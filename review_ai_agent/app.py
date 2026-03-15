from fastapi import FastAPI
from pydantic import BaseModel
from review_ai_agent.agent import agent
import traceback

app = FastAPI()

class ReviewRequest(BaseModel):
    review: str
    email: str
    name: str
   


@app.post("/review")
def run_agent(data: ReviewRequest):

    print(f"Received: {data}")

    try:

        result = agent.invoke({
            "review": data.review,
            "email": data.email,
            "name": data.name,
            

            "sentiment": "",
            "diagnosis": {},
            "ticket_id": "",
            "response": "",
            "history": [],
            "action_plan": {}
        })

        return result

    except Exception as e:

        print(f"Error in agent: {str(e)}")
        print(traceback.format_exc())

        return {
            "sentiment": "neutral",
            "response": f"Error processing review: {str(e)}"
        }