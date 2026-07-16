import json
import os
import random
import shutil
import time
import uuid
from pathlib import Path

from decouple import config
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

from questions import BASE_URL, question_generator
import pyperclip
import re
from typing import List

from bot_runtime import batch_limit


class GenerateQuestions:
    def __init__(self, teardown=False):

        s = Service(ChromeDriverManager().install())
        self.options = webdriver.ChromeOptions()

        # --- Add these two lines here ---
        self.options.add_argument("--headless")
        self.options.add_argument("--window-size=1920,1080")
        # ---------------------------------

        # removed headless so the browser window is visible
        # ensure window is visible and starts maximized
        self.options.add_argument('--start-maximized')
        self.teardown = teardown
        # keep chrome open after chromedriver exits
        self.options.add_experimental_option("detach", True)
        self.options.add_experimental_option(
            "excludeSwitches",
            ['enable-logging'])
        self.driver = webdriver.Chrome(
            options=self.options,
            service=s)
        self.driver.implicitly_wait(50)
        self.collections_url = []
        super(GenerateQuestions, self).__init__()

    def __enter__(self):
        self.driver.get(BASE_URL)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.teardown:
            self.driver.quit()

    def toggle_deep_research(self):
        wait = WebDriverWait(self.driver, 20)

        xpath = '//button[.//span[normalize-space(text())="Fast"]]'
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        btn.click()

        xpath_primary = "//div[@role='menuitem' and .//span[normalize-space(text())='Deep Research']]"
        menu_item = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_primary)))
        menu_item.click()

    def ask_question(self, question_gotten):
        wait = WebDriverWait(self.driver, 1200)
        self.driver.get(BASE_URL)

        wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'form'))
        )

        last_error = None
        for _ in range(int(os.environ.get("DEEPWIKI_ASK_ATTEMPTS", "1"))):
            try:

                # # wait for the form containing the textarea
                form = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'form'))
                )

                # find the textarea inside the form
                textarea = form.find_element(By.CSS_SELECTOR, 'textarea')
                self.toggle_deep_research()
                # type the question
                textarea.click()
                textarea.clear()
                formatted_question = question_generator(question_gotten)

                # Use JavaScript to set the textarea value directly. It's more reliable for large text.
                self.driver.execute_script("arguments[0].value = arguments[1];", textarea, formatted_question)
                # Dispatch an 'input' event to make sure the web application detects the change.
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));",
                                           textarea)
                textarea.send_keys(".. ")

                textarea.send_keys(Keys.ENTER)

                response_wait = WebDriverWait(self.driver, int(os.environ.get("DEEPWIKI_RESPONSE_TIMEOUT", "60")))
                copy_button_selector = (By.CSS_SELECTOR, '[aria-label="Copy"]')
                all_copy_buttons = response_wait.until(
                    EC.presence_of_all_elements_located(copy_button_selector)
                )
                last_copy_button = all_copy_buttons[-1]
                response_wait.until(EC.element_to_be_clickable(last_copy_button)).click()
                try:
                    xpath = "//div[@role='menuitem' and normalize-space(text())='Copy response']"
                    el = WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.XPATH, xpath)))
                    el.click()
                except Exception:
                    pass

                clipboard_content = pyperclip.paste()
                generated_questions = GetQuestions.get_question_content(self, clipboard_content)
                if not generated_questions:
                    raise RuntimeError("DeepWiki answer produced 0 generated audit questions")

                current_url = self.driver.current_url

                # add the current url and inline generated questions to collections
                self.save_to_questions(question_gotten, current_url, generated_questions=generated_questions)
                return current_url
            except Exception as a:
                last_error = a
                print(f"There was an error")
                print(f"{self.driver.current_url}")
                time.sleep(10)
                continue

        fallback_questions = self.fallback_generated_questions(question_gotten)
        print(f"DeepWiki question submission failed; using deterministic fallback questions: {last_error}")
        self.save_to_questions(question_gotten, BASE_URL, generated_questions=fallback_questions)
        return BASE_URL

    def fallback_generated_questions(self, question_gotten):
        raw = str(question_gotten).strip().strip("'")
        file_name = "src/MOG.sol"
        scope = raw
        if "File Name:" in raw and "-> Scope:" in raw:
            try:
                file_name = raw.split("File Name:", 1)[1].split("-> Scope:", 1)[0].strip()
                scope = raw.split("-> Scope:", 1)[1].strip()
            except Exception:
                pass
        prompts = [
            f"[File: {file_name}] Identify any unprivileged path to {scope}; cite exact functions, storage variables, and required transaction sequence.",
            f"[File: {file_name}] Analyze transfer, fee, swapBack, and liquidity logic for {scope}; distinguish intended owner-only behavior from attacker-reachable behavior.",
            f"[File: {file_name}] Check whether fee exemptions, authorization mappings, limits, max wallet/max transaction, or pair/router assumptions create {scope}.",
            f"[File: {file_name}] Review Uniswap V2 pair/router interactions, reserve assumptions, and swap thresholds for {scope}; include concrete proof plan.",
            f"[File: {file_name}] Search for rounding, balance accounting, allowance, burn/dead address, and receiver edge cases that could cause {scope}.",
            f"[File: {file_name}] Compare live_context.json owner, pair, fee, reserve, and balance values with source code assumptions for {scope}.",
            f"[File: {file_name}] Produce likely REJECT cases for {scope} where only owner/admin or excluded roles can trigger the behavior.",
            f"[File: {file_name}] Produce high-confidence candidates for {scope} only if an unprivileged attacker can execute the full exploit path; include Foundry test outline.",
        ]
        return prompts

    def save_to_questions(self, question_gotten, url, generated_questions=None):
        """Save question and URL to questions.json"""
        collections_file = config("SCOPE_QUESTIONS_PATH")

        # Load existing data or start fresh
        try:
            if os.path.exists(collections_file):
                with open(collections_file, "r") as f:
                    content = f.read().strip()
                    data = json.loads(content) if content else []
            else:
                data = []
        except json.JSONDecodeError:
            print("Invalid questions.json, creating new file")
            data = []

        # Add new entry
        entry = {
            "question": question_gotten,
            "url": url,
            "questions_generated": False
        }
        if generated_questions:
            entry["generated_questions"] = generated_questions
        data.append(entry)

        # Save with proper formatting
        try:
            with open(collections_file, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving to collections: {e}")
            raise


class GetQuestions:
    def __init__(self, teardown=False):

        s = Service(ChromeDriverManager().install())
        self.options = webdriver.ChromeOptions()

        # --- Add these two lines here ---
        # self.options.add_argument("--headless")
        # self.options.add_argument("--window-size=1920,1080")
        # ---------------------------------

        # removed headless so the browser window is visible
        # ensure window is visible and starts maximized
        self.options.add_argument('--start-maximized')
        self.teardown = teardown
        # keep chrome open after chromedriver exits
        self.options.add_experimental_option("detach", True)
        self.options.add_experimental_option(
            "excludeSwitches",
            ['enable-logging'])
        self.driver = webdriver.Chrome(
            options=self.options,
            service=s)
        self.driver.implicitly_wait(50)
        self.collections_url = []
        super(GetQuestions, self).__init__()

    def get_questions(self, url):
        question_directory = os.environ.get('QUESTION_DIR', 'question')
        os.makedirs(question_directory, exist_ok=True)

        try:
            self.driver.get(url)

            wait = WebDriverWait(self.driver, 60)

            def save_debug(reason: str) -> Path:
                debug_dir = Path(os.environ.get("DEEPWIKI_DEBUG_DIR", "deepwiki_debug"))
                debug_dir.mkdir(parents=True, exist_ok=True)
                base = debug_dir / f"{uuid.uuid4().hex}_{reason}"
                try:
                    (base.with_suffix(".html")).write_text(self.driver.page_source or "", encoding="utf-8")
                except Exception:
                    pass
                try:
                    self.driver.save_screenshot(str(base.with_suffix(".png")))
                except Exception:
                    pass
                return base

            # Wait for the final answer/copy UI to exist. DeepWiki can be slow to hydrate
            # after CAPTCHA/indexing, so wait longer than Selenium's implicit timeout.
            copy_button_selector = (By.CSS_SELECTOR, '[aria-label="Copy"]')
            try:
                all_copy_buttons = wait.until(EC.presence_of_all_elements_located(copy_button_selector))
            except TimeoutException as exc:
                base = save_debug("no_copy_button")
                title = self.driver.title
                current = self.driver.current_url
                body_text = self.driver.find_element(By.TAG_NAME, "body").text[:2000] if self.driver.find_elements(By.TAG_NAME, "body") else ""
                raise RuntimeError(
                    f"DeepWiki page did not expose a Copy button. title={title!r} current_url={current!r} "
                    f"debug_base={base} body_start={body_text!r}"
                ) from exc

            last_copy_button = all_copy_buttons[-1]
            wait.until(EC.element_to_be_clickable(last_copy_button)).click()

            xpath = "//div[@role='menuitem' and normalize-space(text())='Copy response']"
            try:
                el = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                el.click()
            except TimeoutException:
                # Some DeepWiki builds copy directly from the button and do not show a menu.
                pass

            clipboard_content = pyperclip.paste()

            all_questions = self.get_question_content(clipboard_content)
            if not all_questions:
                debug_dir = Path(os.environ.get("DEEPWIKI_DEBUG_DIR", "deepwiki_debug"))
                debug_dir.mkdir(parents=True, exist_ok=True)
                debug_file = debug_dir / f"{uuid.uuid4().hex}_empty_response.txt"
                debug_file.write_text(
                    "URL: " + url + "\n\n" + (clipboard_content or "<empty clipboard>"),
                    encoding="utf-8",
                )
                raise RuntimeError(
                    f"DeepWiki response produced 0 extracted questions for {url}; "
                    f"debug saved to {debug_file}"
                )

            try:
                # Split into chunks of 25
                chunk_size = 25
                total_questions = len(all_questions)

                for i in range(0, total_questions, chunk_size):
                    # Get a chunk of 25 questions
                    chunk = all_questions[i:i + chunk_size]

                    # Generate a unique filename
                    filename = f"{str(uuid.uuid4())}.json".replace("-", "")
                    filepath = os.path.join(question_directory, filename)

                    # Save the chunk to a new file
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(chunk, f, indent=2, ensure_ascii=False)

                    print(f"Saved {len(chunk)} questions to {filepath}")

                print(
                    f"\nSuccessfully split {total_questions} questions into {((total_questions - 1) // chunk_size) + 1} files")
            except Exception as a:
                print(a)

        except Exception as e:
            raise RuntimeError(f"Failed to generate question report for {url}: {e}") from e

    def get_question_content(self, clip_board_content: str) -> List[str]:
        """
            Extracts security audit questions from the provided text using regex.
            """
        pattern = r'"(\[File:.*?)"'
        questions = re.findall(pattern, clip_board_content, flags=re.DOTALL)
        # Optional: Clean up whitespace (strip) for each question found
        return [q.strip() for q in questions]


def generate_file_path_for_scope():
    # Get the directory from environment variable, or use 'questions' as default
    scope_questions_directory = os.environ.get('SCOPE_QUESTIONS_DIR', 'scope_questions')
    scope_directory = os.environ.get("QUESTION_DIR", 'scope')
    scope_pending_directory = os.environ.get("SCOPE_PENDING_DIR", 'scope_pending')

    # Create the directories if they don't exist
    os.makedirs(scope_questions_directory, exist_ok=True)
    os.makedirs(scope_directory, exist_ok=True)
    os.makedirs(scope_pending_directory, exist_ok=True)

    scope_files = sorted(Path(scope_directory).glob('*.json'))

    if not scope_files:
        raise FileNotFoundError(f"No scope files found in {scope_directory}")

    # Get the first file
    source_file = random.choice(scope_files)
    file_name = source_file.name

    # Define destination path in pending directory
    destination_file = Path(scope_pending_directory) / file_name
    questions_file = f"{source_file.stem}.json"  # Keep the same filename but ensure .json extension

    try:
        # Move the file to pending directory
        source_file.rename(destination_file)
        print(f"Moved {file_name} to {scope_pending_directory}")
    except Exception as e:
        raise IOError(f"Failed to move {file_name} to {scope_pending_directory}: {e}")

    # Generate file path
    file_path = os.path.join(scope_questions_directory, questions_file)

    # Create or update .env file with the file path
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    with open(env_path, 'w') as f:
        f.write(f"SCOPE_QUESTIONS_PATH={file_path}\n")

    os.environ['SCOPE_QUESTIONS_PATH'] = file_path
    print(os.environ.get('SCOPE_QUESTIONS_PATH'))

    return str(questions_file)


def generate_file_path_get_questions():
    question_directory = os.environ.get("QUESTIONS_DIR", "questions")
    scope_questions_directory = os.environ.get('SCOPE_QUESTIONS_DIR', 'scope_questions')
    scope_questions_pending_directory = os.environ.get("SCOPE_QUESTIONS_PENDING_DIR", 'scope_questions_pending')

    # Create the directories if they don't exist
    os.makedirs(question_directory, exist_ok=True)
    os.makedirs(scope_questions_directory, exist_ok=True)
    os.makedirs(scope_questions_pending_directory, exist_ok=True)

    # Get all JSON files in the questions directory
    questions_files = sorted(Path(scope_questions_directory).glob('*.json'))

    if not questions_files:
        raise FileNotFoundError("No questions files found")

    moved_files = []
    counter = 0

    max_files = batch_limit(20)
    for file_path in questions_files:
        try:
            if counter >= max_files:
                break

            # Create destination path
            dest_path = os.path.join(scope_questions_pending_directory, file_path.name)

            # Skip if file with same name already exists in destination
            if os.path.exists(dest_path):
                # Append a timestamp to make filename unique
                base_name = file_path.stem
                extension = file_path.suffix
                timestamp = int(time.time())
                dest_path = os.path.join(scope_questions_pending_directory, f"{base_name}_{timestamp}{extension}")

            # Move the file
            shutil.move(str(file_path), dest_path)
            moved_files.append(dest_path)
            counter += 1
            print(f"Moved {file_path} to {dest_path}")

        except Exception as e:
            print(f"Error moving {file_path}: {e}")
            continue

    if not moved_files:
        print("No files were moved")
        return None

    print(f"Successfully moved {len(moved_files)} files to {scope_questions_pending_directory}")
    return moved_files
