from pathlib import Path
from pydantic import BaseModel
from core.agent import load_agents
from core.log import get_logger
from core.verify import verify

TASK_NAME = "example"
TASK_DIR = Path(__file__).parent
log = get_logger(TASK_NAME)


class Answer(BaseModel):
    answer: str


def run():
    agents = load_agents(TASK_DIR)
    solver = agents["solver"]

    @solver.tool
    def get_sky_color() -> str:
        """Returns the color of the sky."""
        return "blue"

    solver.context.add_system(
        "Important: answer should always be a single word.",
        pinned=True,
        tag="task_data",
    )

    result = solver.run(
        'What is the color of the sky? Use the tool. Respond as JSON: {"answer": "..."}',
        output_type=Answer,
    )
    log.info("Answer: %s", result.answer)

    return verify(TASK_NAME, result.answer)
