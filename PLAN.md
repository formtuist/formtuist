# Plan for Implementing Formtuitous

This is a plan for building Formtuitous, a tool that lets you:

- Using a standard text editor, a person like me would specify a form (e.g., a
  survey or a quiz) in JSON format. This is a precursor step to actually running
  the `formtuitous` application.
- Using a command like `uvx formtuitous`, the program will automatically
  generate a TUI representation of the survey encoded in the JSON file.
- Using the `textual` package, the program will display the survey in a
  terminal-based user interface (TUI) and allow the user to fill it out.
- If the person using the program chooses to do so, they can ask `formtuitous`
  to use the `textual-serve` package to serve the survey as a web application.
- A person can then use a web browser to fill out the survey and submit their
  responses. (Don't worry about how a person accesses it through their web
  browser, my plan is to make it available through a cloudflare tunnel. But, that
  is not something that needs to be a specific part of the plan for implementing
  Formtuitous.)
- Once the form has been filled out and submitted, the program will save the
  responses in a JSON file. The program will also provide an option to export the
  responses in CSV or the sqlite database format.
- The tool will also have a mode that uses datasette to make it possible for
  someone to view the responses in a web browser. This will be done by using
  datasette to serve the responses as a web application.

As an analogy, the benefits of Formtuitous are the following:

- Easy to specify a form using a text editor in JSON.
- Easy to fill out the form in a terminal window or a web browser.
- Easy to view the responses in a text editor or a web browser.

I need this type of tool because I am a Software Engineering and Computer
Science professor who makes a lot of surveys for:

- Attendance taking
- In person assessments
- Reports from demonstrations
- Short quizzes

I really hate using Google Forms! I want to build a tool that is roughly
inspired by Google Forms. But, it should have all the benefits that I have
outlined in this plan. The purpose of Formtuitous is not to ultimately upload
data to a Google Sheet or to create a Google Form. It is its own stand-alone
system that you can use as a simple and fun replacement for Google Forms.

There are the technologies employed in Formtuitous, which is a Python-based
application:

- Application dependencies:
  - Python
  - uv
  - rich
  - textual
  - textual-serve
- Development dependencies:
  - pytest for test suite execution
  - pyrefly, ty, mypy, and zuban for LSP and or type checking
  - hypothesis for property-based testing
  - rumdl for markdown linting
  - pytest-cov for test coverage monitoring

Here are some details about the JSON format for specifying a form:

- Name of the form
- Configuration details about the display of the form:
  - Whether or not questions are displayed in a random order
  - Whether or not the questions are automatically graded
  - Other configuration details that you deem to be important
- A list of the questions for the form, with details about:
  - Unique identifier for the question
  - The text of the actual question
  - The data type of the answer
  - Whether or not the answer is required
  - The choices for the answer (if applicable)
- Extra information to display along with the question:
  - A source code segment to be displayed with syntax highlighting
  - An image to be displayed with the question
  - A reference to a URL for the question
