# Project Title

Micro-narrative Chatbot Framework

## Description

This repository contains an open-source Streamlit application for running LLM-powered micro-narrative collection and refinement. The app guides a user through:

1. Providing a short story or reflection (a “micro-narrative”)
2. Refining and summarising the content into multiple scenarios
3. Reviewing and adapting the final output

The framework is designed for flexibility — prompts, conversation flows, and scenario-generation styles can be adapted for different domains and topics.

**Note:** This is an open-source version. A separate licensed production build exists with additional features and infrastructure for large-scale deployments.

---

## File Overview

1. **interaction\_prototype.py** — Main Streamlit app code; builds the chained LLM conversation flow.
2. **lc\_prompts.py** — Base prompts for guiding narrative elicitation and summarisation.
3. **lc\_scenario\_prompts.py** — Persona-based prompts for generating alternative scenario styles.
4. **testing\_prompts.py** — Example prompts and test data for debugging and demonstration.
5. **requirements.txt** — Full list of dependencies with pinned versions.

---

## Installation

1. Clone this repository:

   ```bash
   git clone https://github.com/miz-art/Micro-narrativesxHarms_June25.git
   cd Micro-narrativesxHarms_June25
   ```
2. Create and activate a virtual environment:

   ```bash
   python3 -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   ```
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```
4. Create a `.streamlit/secrets.toml` file with your API keys (template available on request).
5. Run the app:

   ```bash
   streamlit run app.py
   ```

---

## Demo

A public demo (safe test mode) is available:
[https://2024-app-modular-hmu7ey5xum4j7ddbj3mv4e.streamlit.app/](https://2024-app-modular-hmu7ey5xum4j7ddbj3mv4e.streamlit.app/)

The demo allows you to:

* Enter any responses to the chatbot prompts
* Follow the full interaction flow: consent → storytelling → scenario generation → review → finalisation
* Explore the framework’s output without storing real data

---

## License

* Academic and Non-Profit Use Only — No commercial use permitted
* For licensing queries (including the production version), contact the maintainers

---

If you want, I can also make this README include **a “Customisation” section** so developers know exactly which files to edit to change prompts, scenario styles, and output formats. That would make it more useful for open-source adoption.

Do you want me to add that?
