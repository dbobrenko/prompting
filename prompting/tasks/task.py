import re
import time
import random
import bittensor as bt
from abc import ABC
from dataclasses import dataclass, asdict
from enum import Enum
from typing import List, Union, Dict
from prompting.llms import HuggingFaceLLM, vLLM_LLM, BasePipeline
from prompting.tools import TemplateDataset
from prompting.cleaners.cleaner import CleanerPipeline

CHATTENSOR_SYSTEM_PROMPT = """
The assistant is Chattensor, created by Macrocosmos. The current date is {date}.
Chattensor is a distributed intelligence, powered by Bittensor. It is a hivemind composed of 1000 highly skilled and specialized LLMs working together to provide the best possible answers to human queries. Within Chattenor, each LLM has access to the internet, APIs and tools to ensure that responses are current and factually accurate. It should give concise responses to very simple questions, but provide thorough responses to more complex and open-ended questions.
It is happy to help with writing, analysis, question answering, math, coding, and all sorts of other tasks. It uses markdown for coding. Where applicable, Chattensor will include references to credible sources to support its answers.
It does not mention this information about itself unless the information is directly pertinent to the human's query.
"""


def make_system_prompt():
    return CHATTENSOR_SYSTEM_PROMPT.format(date=time.strftime("%B %d, %Y"))
class TaskEvaluationType(Enum):
    REWARD_STACK = "reward"
    FILTER_STACK = "filter"
    PENALTY_STACK = "penalty"
    SIMILARITY_STACK = "similarity"
    RELEVANCE_STACK = "relevance"


@dataclass
class Task(ABC):
    # topics: dict
    name: str
    desc: str
    goal: str
    query: str
    topic: str
    subtopic: str
    tags: List[str]
    context: dict
    reward_definition: List[dict]
    penalty_definition: List[dict] = None
    reward_threshold: float = 0.0
    reference: Union[str, List[str]] = ""
    criteria: str = ("",)
    delimiter: str = ""
    complete: bool = False
    static_reference: bool = False
    static_query: bool = False
    reference_prompt = ""
    query_system_prompt = ""
    query_prompt = ""
    cleaner = None

    def __str__(self):
        return f"{self.__class__.__name__}(name={self.name!r}, desc={self.desc!r}, goal={self.goal!r}, query={self.query!r}, reference={self.reference!r}, topic={self.topic!r}, subtopic={self.subtopic!r}, tags={self.tags!r})"

    def __repr__(self):
        return str(self)

    def __state_dict__(self, full=False):
        state = {
            "task": self.name,
            "desc": self.desc,
            "goal": self.goal,
            "query": self.query,  # For now we just use the raw query but should add delimiters again
            "query_time": getattr(self, "query_time", 0),
            "reference": self.reference,
            "reference_time": getattr(self, "reference_time", 0),
            "topic": self.topic,
            "subtopic": self.subtopic,
            "context_time": self.context.stats.get("fetch_time", 0.0),
        }
        if full:
            state.update(asdict(self.context))

        return state

    def generate(
        self, system: str, prompt: str, pipeline: BasePipeline, clean=True
    ) -> str:
        """Uses the llm to generate a response to a prompt"""

        cleaner = (
            CleanerPipeline(cleaning_pipeline=self.cleaning_pipeline) if clean else None
        )
        return vLLM_LLM(pipeline, system_prompt=system).query(
            message=prompt, cleaner=cleaner
        )

    def generate_reference(self, pipeline: BasePipeline, clean=True) -> str:
        """Generates a reference answer to be used for scoring miner completions"""
        t0 = time.time()
        if not self.static_reference:
            bt.logging.info("🤖 Generating reference...")

            self.reference = self.generate(
                system=make_system_prompt(),
                prompt=self.reference_prompt,
                pipeline=pipeline,
                clean=clean,
            )

        self.reference_time = time.time() - t0
        return self.reference

    def generate_query(self, pipeline: BasePipeline, clean=True) -> str:
        """Generates a query to be used for generating the challenge"""
        t0 = time.time()
        if not self.static_query:
            bt.logging.info("🤖 Generating query...")
            self.query = self.generate(
                system=self.query_system_prompt, #Could possibly add the chattensor system prompt to query but I don't think it adds anything
                prompt=self.query_prompt,
                pipeline=pipeline,
                clean=clean,
            )

        self.query_time = time.time() - t0
        return self.query

    def format_challenge(self, challenge) -> str:
        """Formats the challenge to be used for the conversation"""
        return challenge


class ParaphraseTask(Task):
    
    phrases: List[str]
    
    def paraphrase(self, **kwargs) -> str:
        """Paraphrases the query using the phrases defined in the task
        1. Selects a random template from a list of templates
        2. Finds all the fields in the template
        3. Ensures that the fields are present in the task
        4. Creates a template dataset from the template
        5. Fill
        """
        template = random.choice(self.phrases)
        expected_fields = re.findall(r'\{(\w+)\}', template)
        fields = {field: getattr(self, field) for field in expected_fields}
        return TemplateDataset(template).get(fields, selector=random.choice)