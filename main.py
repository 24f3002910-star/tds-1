
import os
import sys
import traceback
from io import StringIO
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from google.genai import types

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CodeRequest(BaseModel):
    code: str


class CodeResponse(BaseModel):
    error: List[int]
    result: str


class ErrorAnalysis(BaseModel):
    error_lines: List[int]


def execute_python_code(code: str) -> dict:
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    captured_stdout = StringIO()
    captured_stderr = StringIO()

    try:
        sys.stdout = captured_stdout
        sys.stderr = captured_stderr

        exec(compile(code, "<string>", "exec"), {})

        return {
            "success": True,
            "output": captured_stdout.getvalue()
        }

    except Exception:
        return {
            "success": False,
            "output": traceback.format_exc()
        }

    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def analyze_error_with_ai(code: str, error_traceback: str) -> List[int]:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    prompt = f"""
Identify the Python source line numbers responsible for the
exception. Return only line numbers from the submitted code.
Use the final relevant traceback frame and do not count traceback
header lines as source lines.

CODE:
{code}

TRACEBACK:
{error_traceback}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ErrorAnalysis,
        ),
    )

    analysis = ErrorAnalysis.model_validate_json(response.text)
    total_lines = len(code.splitlines())

    return sorted(set(
        line for line in analysis.error_lines
        if 1 <= line <= total_lines
    ))


@app.post("/code-interpreter", response_model=CodeResponse)
def code_interpreter(request: CodeRequest):
    execution = execute_python_code(request.code)

    if execution["success"]:
        return {"error": [], "result": execution["output"]}

    try:
        lines = analyze_error_with_ai(
            request.code,
            execution["output"]
        )
    except Exception:
        lines = []

    return {
        "error": lines,
        "result": execution["output"]
    }
