"""
Micro-narrative Chatbot - Streamlit App

This application guides users through a multi-step process of sharing and refining narratives
about challenging experiences on social media. It leverages LangChain, Streamlit, and AWS services 
to collect, extract, summarise, and evaluate user stories using LLM-systems, with real-time feedback and interaction.

Key technologies:
- LangChain & LangSmith for LLM orchestration and tracing
- Streamlit for interactive frontend
- AWS DynamoDB for backend data storage
"""

# === LangChain & LangSmith: LLM orchestration and memory management ===
from langchain_community.chat_message_histories import StreamlitChatMessageHistory
from langchain.memory import ConversationBufferMemory
from langchain_core.prompts import PromptTemplate
from langchain.chains import ConversationChain
from langchain_openai import ChatOpenAI
from langchain.output_parsers.json import SimpleJsonOutputParser
from langsmith import Client
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

# === Streamlit Feedback Integration ===
from streamlit_feedback import streamlit_feedback

# === AWS SDK (Boto3) for data storage ===
import boto3
from botocore.exceptions import ClientError

# === Python Standard Library ===
import random
from datetime import datetime
from functools import partial
import os

# === Streamlit UI ===
import streamlit as st

# === Project Modules ===
## import our prompts: 
from lc_prompts import *
from lc_scenario_prompts import *
from testing_prompts import * 



# Using streamlit secrets to set environment variables for langsmith/chain
os.environ["OPENAI_API_KEY"] = st.secrets['OPENAI_API_KEY']
os.environ["LANGCHAIN_API_KEY"] = st.secrets['LANGCHAIN_API_KEY']
os.environ["LANGCHAIN_PROJECT"] = st.secrets['LANGCHAIN_PROJECT']
os.environ["LANGCHAIN_TRACING_V2"] = 'true'
os.environ["AWS_ACCESS_KEY_ID"] = st.secrets['AWS_ACCESS_KEY_ID']
os.environ["AWS_SECRET_ACCESS_KEY"] = st.secrets['AWS_SECRET_ACCESS_KEY']
os.environ["AWS_DEFAULT_REGION"] = st.secrets['AWS_DEFAULT_REGION']

# Initialize table
dynamodb = boto3.resource(
    'dynamodb',
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    region_name=os.environ["AWS_DEFAULT_REGION"]
)
table = dynamodb.Table('petr_micronarrative_nov2024')

## simple switch previously used to help debug 
DEBUG = False

# Langsmith set-up 
smith_client = Client()

st.set_page_config(page_title="Study bot", page_icon="📖")
st.title("📖 Study bot")

def make_chat_id():
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    if "pid" in st.query_params:
        prolific_id = st.query_params["pid"]
    else:
        prolific_id = '00000'
    chat_id = f'{prolific_id}'
    return chat_id

if "chat_id" not in st.session_state:
    st.session_state["chat_id"] = make_chat_id()
    st.session_state["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
init_state = {
    "run_id": None,
    "agentState": "start",
    "consent": False,
    "exp_data": True,
    "llm_model": "gpt-4o"#,
    # "col1_fb": {"score": "", "text": ""},
    # "col2_fb": {"score": "", "text": ""},
    # "col3_fb": {"score": "", "text": ""}
    
}

for key, value in init_state.items():
    if key not in st.session_state:
        st.session_state[key] = value

    

# Set up memory for the lanchchain conversation bot
msgs = StreamlitChatMessageHistory(key="langchain_messages")
memory = ConversationBufferMemory(memory_key="history", chat_memory=msgs)



## ensure we are using a better prompt for 4o 
if st.session_state['llm_model'] == "gpt-4o":
    prompt_datacollection = prompt_datacollection_4o



def getData (testing = False ): 
    """Collects answers to main questions from the user. 
    
    The conversation flow is stored in the msgs variable (which acts as the persistent langchain-streamlit memory for the bot). The prompt for LLM must be set up to return "FINISHED" when all data is collected. 
    
    Parameters: 
    testing: bool variable that will insert a dummy conversation instead of engaging with the user

    Returns: 
    Nothing returned as all data is stored in msgs. 
    """

    ## if this is the first run, set up the intro 
    if len(msgs.messages) == 0:
        msgs.add_ai_message("Hi there -- I'm collecting stories about challenging experiences on social media to better understand and support young people. I'd appreciate if you could share your experience with me by answering a few questions. _If you can't think of a personal experience, you can share something that has happened to a friend or someone you know but remember not to share any personally identifible information._ \n\n I'll start with a general question and then we'll move to a specific situation you remember. \n\n  Let me know when you're ready! ")


   # as Streamlit refreshes page after each input, we have to refresh all messages. 
   # in our case, we are just interested in showing the last AI-Human turn of the conversation for simplicity

    if len(msgs.messages) >= 2:
        last_two_messages = msgs.messages[-1:]
    else:
        last_two_messages = msgs.messages

    for msg in last_two_messages:
        if msg.type == "ai":
            with entry_messages:
                st.chat_message(msg.type).write(msg.content)


    # If user inputs a new answer to the chatbot, generate a new response and add into msgs
    if prompt:
        # Note: new messages are saved to history automatically by Langchain during run 
        with entry_messages:
            # show that the message was accepted 
            st.chat_message("human").write(prompt)
            msg = {"role": "human", "content": prompt}
            # append_list_entry(st.session_state["chat_id"], "interview_chat", msg)
            
            
            # generate the reply using langchain 
            response = conversation.invoke(input = prompt)
            
            # the prompt must be set up to return "FINISHED" once all questions have been answered
            # If finished, move the flow to summarisation, otherwise continue.
            if "FINISHED" in response['response']:
                st.divider()
                st.chat_message("ai").write("Thank you for sharing your experience with us.")

                # call the summarisation  agent
                st.session_state.agentState = "summarise"
                summariseData(testing)
            else:
                st.chat_message("ai").write(response["response"])
                msg = {"role": "assistant", "content": response["response"]}
                # append_list_entry(st.session_state["chat_id"], "interview_chat", msg)

 
        
        #st.text(st.write(response))


def extractChoices(msgs, testing ):
    """Uses bespoke LLM prompt to extract answers to given questions from a conversation history into a JSON object. 

    Arguments: 
    msgs (str): conversations history to extract from -- this can be streamlit memory, or a dummy variable during testing
    testing (bool): bool variable that will insert a dummy conversation instead of engaging with the user

    """

    ## set up our extraction LLM -- low temperature for repeatable results
    extraction_llm = ChatOpenAI(temperature=0.1, model=st.session_state.llm_model, openai_api_key=openai_api_key)

    ## taking the prompt from lc_prompts.py file
    extraction_template = PromptTemplate(input_variables=["conversation_history"], template = extraction_prompt)

    ## set up the rest of the chain including the json parser we will need. 
    json_parser = SimpleJsonOutputParser()
    extractionChain = extraction_template | extraction_llm | json_parser

    
    # allow for testing the flow with pre-generated messages -- see testing_prompts.py
    if testing:
        extractedChoices = extractionChain.invoke({"conversation_history" : test_messages})
    else: 
        extractedChoices = extractionChain.invoke({"conversation_history" : msgs})
    

    return(extractedChoices)


def collectFeedback(answer, column_id,  scenario):
    """ Submits user's feedback on specific scenario to langsmith; called as on_submit function for the respective streamlit feedback object. 
    
    The payload combines the text of the scenario, user output, and answers. This function is intended to be called as 'on_submit' for the streamlit_feedback component.  

    Parameters: 
    answer (dict): Returned by streamlit_feedback function, contains "the user response, with the feedback_type, score and text fields" 
    column_id (str): marking which column this belong too 
    scenario (str): the scenario that users submitted feedback on

    """

    st.session_state.temp_debug = "called collectFeedback"
    # print('answer', answer)
    
    
    
    # allows us to pick between thumbs / faces, based on the streamlit_feedback response
    score_mappings = {
        "thumbs": {"👍": 1, "👎": 0},
        "faces": {"😀": 1, "🙂": 0.75, "😐": 0.5, "🙁": 0.25, "😞": 0},
    }
    scores = score_mappings[answer['type']]
    
    # update_db_entry(st.session_state["chat_id"], f'rating_{column_id}', answer)
    
    # Get the score from the selected feedback option's score mapping
    score = scores.get(answer['score'])

    # store the Langsmith run_id so the feedback is attached to the right flow on Langchain side 
    run_id = st.session_state['run_id']

    if DEBUG: 
        st.write(run_id)
        st.write(answer)


    if score is not None:
        # Formulate feedback type string incorporating the feedback option
        # and score value
        feedback_type_str = f"{answer['type']} {score} {answer['text']} \n {scenario}"
        
        

        st.session_state.temp_debug = feedback_type_str

        ## combine all data that we want to store in Langsmith
        payload = f"{answer['score']} rating scenario: \n {scenario} \n Based on: \n {answer_set}"

        # Record the feedback with the formulated feedback type string
        # and optional comment
        smith_client.create_feedback(
            run_id= run_id,
            value = payload,
            key = column_id,
            score=score,
            comment=answer['text']
        )
    else:
        st.warning("Invalid feedback score.")    



@traceable # Auto-trace this function
def summariseData(testing = False): 
    """Takes the extracted answers to questions and generates three scenarios, based on selected prompts. 

    testing (bool): will insert a dummy data instead of user-generated content if set to True

    """


    # start by setting up the langchain chain from our template (defined in lc_prompts.py)
    prompt_template = PromptTemplate.from_template(prompt_one_shot)

    # add a json parser to make sure the output is a json object
    json_parser = SimpleJsonOutputParser()

    # connect the prompt with the llm call, and then ensure output is json with our new parser
    chain = prompt_template | chat | json_parser

    # ## pick the prompt we want to use 
    # prompt_1 = prompts['prompt_1']
    # prompt_2 = prompts['prompt_2']
    # prompt_3 = prompts['prompt_3']
    
    # pick the prompt we want to use (counterbalance order)
    prompt_type_1, prompt_type_2, prompt_type_3 = random.sample(['formal', 'youngsib', 'friend'], 3)
    prompt_1, prompt_2, prompt_3 = prompts[prompt_type_1], prompts[prompt_type_2], prompts[prompt_type_3]
    # update_db_entry(st.session_state["chat_id"], "prompt_type_1", prompt_type_1)
    # update_db_entry(st.session_state["chat_id"], "prompt_type_2", prompt_type_2)
    # update_db_entry(st.session_state["chat_id"], "prompt_type_3", prompt_type_3)
    
    
    
    end_prompt = end_prompt_core

    ### call extract choices on real data / stored test data based on value of testing
    if testing: 
        answer_set = extractChoices(msgs, True)
    else:
        answer_set = extractChoices(msgs, False)
    
    ## debug shows the interrim steps of the extracted set
    if DEBUG: 
        st.divider()
        st.chat_message("ai").write("**DEBUGGING** *-- I think this is a good summary of what you told me ... check if this is correct!*")
        st.chat_message("ai").json(answer_set)

    # store the generated answers into streamlit session state
    st.session_state['answer_set'] = answer_set


    # let the user know the bot is starting to generate content 
    with entry_messages:
        if testing:
            st.markdown(":red[DEBUG active -- using testing messages]")

        st.divider()
        st.chat_message("ai").write("Seems I have everything! Let me try to summarise what you said in three scenarios. \n See you if you like any of these! ")


        ## can't be bothered to set up LLM stream here, so just showing progress bar for now  
        ## this gets manually updated after each scenario
        progress_text = 'Processing your scenarios'
        bar = st.progress(0, text = progress_text)


    # create first scenario & store into st.session state 
    st.session_state.response_1 = chain.invoke({
        "main_prompt" : prompt_1,
        "end_prompt" : end_prompt,
        "example_what" : example_set['what'],
        "example_context" : example_set['context'],
        "example_outcome" : example_set['outcome'],
        "example_reaction" : example_set['reaction'],
        "example_scenario" : example_set['scenario'],
        "what" : answer_set['what'],
        "context" : answer_set['context'],
        "outcome" : answer_set['outcome'],
        "reaction" : answer_set['reaction']
    })
    run_1 = get_current_run_tree()

    ## update progress bar
    bar.progress(33, progress_text)

    st.session_state.response_2 = chain.invoke({
        "main_prompt" : prompt_2,
        "end_prompt" : end_prompt,
        "example_what" : example_set['what'],
        "example_context" : example_set['context'],
        "example_outcome" : example_set['outcome'],
        "example_reaction" : example_set['reaction'],
        "example_scenario" : example_set['scenario'],
        "what" : answer_set['what'],
        "context" : answer_set['context'],
        "outcome" : answer_set['outcome'],
        "reaction" : answer_set['reaction']
    })
    run_2 = get_current_run_tree()

    ## update progress bar
    bar.progress(66, progress_text)

    st.session_state.response_3 = chain.invoke({
        "main_prompt" : prompt_3,
        "end_prompt" : end_prompt,
        "example_what" : example_set['what'],
        "example_context" : example_set['context'],
        "example_outcome" : example_set['outcome'],
        "example_reaction" : example_set['reaction'],
        "example_scenario" : example_set['scenario'],
        "what" : answer_set['what'],
        "context" : answer_set['context'],
        "outcome" : answer_set['outcome'],
        "reaction" : answer_set['reaction']
    })
    run_3 = get_current_run_tree()

    ## update progress bar after the last scenario
    bar.progress(99, progress_text)

    # remove the progress bar
    # bar.empty()

    if DEBUG: 
        st.session_state.run_collection = {
            "run1": run_1,
            "run2": run_2,
            "run3": run_3
        }

    ## update the correct run ID -- all three calls share the same one. 
    st.session_state.run_id = run_1.id

    ## move the flow to the next state
    st.session_state["agentState"] = "review"

    # we need the user to do an action (e.g., button click) to generate a natural streamlit refresh (so we can show scenarios on a clear page). Other options like streamlit rerun() have been marked as 'failed runs' on Langsmith which is annoying. 
    st.button("I'm ready -- show me!", key = 'progressButton')
    
    # Save scenario proposals to the database
    # update_db_entry(st.session_state["chat_id"], "scenario_1", st.session_state.response_1['output_scenario'])
    # update_db_entry(st.session_state["chat_id"], "scenario_2", st.session_state.response_2['output_scenario'])
    # update_db_entry(st.session_state["chat_id"], "scenario_3", st.session_state.response_3['output_scenario'])


def testing_reviewSetUp():
    """Simple function that just sets up dummy scenario data, used when testing later flows of the process. 
    """
    

    ## setting up testing code -- will likely be pulled out into a different procedure 
    text_scenarios = {
        "s1" : "So, here's the deal. I've been really trying to get my head around this coding thing, specifically in langchain. I thought I'd share my struggle online, hoping for some support or advice. But guess what? My PhD students and postdocs, the very same people I've been telling how crucial it is to learn coding, just laughed at me! Can you believe it? It made me feel super ticked off and embarrassed. I mean, who needs that kind of negativity, right? So, I did what I had to do. I let all the postdocs go, re-advertised their positions, and had a serious chat with the PhDs about how uncool their reaction was to my coding struggles.",

        "s2": "So, here's the thing. I've been trying to learn this coding thing called langchain, right? It's been a real struggle, so I decided to share my troubles online. I thought my phd students and postdocs would understand, but instead, they just laughed at me! Can you believe that? After all the times I've told them how important it is to learn how to code. It made me feel really mad and embarrassed, you know? So, I did what I had to do. I told the postdocs they were out and had to re-advertise their positions. And I had a serious talk with the phds, telling them that laughing at my coding struggles was not cool at all.",

        "s3": "So, here's the deal. I've been trying to learn this coding language called langchain, right? And it's been a real struggle. So, I decided to post about it online, hoping for some support or advice. But guess what? My PhD students and postdocs, the same people I've been telling how important it is to learn coding, just laughed at me! Can you believe it? I was so ticked off and embarrassed. I mean, who does that? So, I did what any self-respecting person would do. I fired all the postdocs and re-advertised their positions. And for the PhDs? I had a serious talk with them about how uncool their reaction was to my coding struggles."
    }

    # insert the dummy text into the right st.sessionstate locations 
    st.session_state.response_1 = {'output_scenario': text_scenarios['s1']}
    st.session_state.response_2 = {'output_scenario': text_scenarios['s2']}
    st.session_state.response_3 = {'output_scenario': text_scenarios['s3']}


def click_selection_yes(button_num, scenario):
    """ Function called on_submit when a final scenario is selected. 
    
    Saves all key information in the st.session_state.scenario_package persistent variable.
    """
    st.session_state.scenario_selection = button_num
    
    # Save scenario choice to the database
    # update_db_entry(st.session_state["chat_id"], "scenario_choice", button_num)
    
    ## if we are testing, the answer_set might not have been set & needs to be added:
    if 'answer_set' not in st.session_state:
        st.session_state['answer_set'] = "Testing - no answers"

    ## save all important information in one package into st.session state

    scenario_dict = {
        'col1': st.session_state.response_1['output_scenario'],
        'col2': st.session_state.response_2['output_scenario'],
        'col3': st.session_state.response_3['output_scenario'],
        'fb1': st.session_state['col1_fb'],
        'fb2': st.session_state['col2_fb'],
        'fb3': st.session_state['col3_fb']
    }
    
    # Save thumbs and optional text to the database
    
    # update_db_entry(st.session_state["chat_id"], "thumb_1", scenario_dict['fb1'])
    # update_db_entry(st.session_state["chat_id"], "thumb_2", scenario_dict['fb2'])
    # update_db_entry(st.session_state["chat_id"], "thumb_3", scenario_dict['fb3'])
    # # update_db_entry(st.session_state["chat_id"], "thumb_1_text", st.session_state['col1_fb']['text'])
    # update_db_entry(st.session_state["chat_id"], "thumb_2_text", st.session_state['col2_fb']['text'])
    # update_db_entry(st.session_state["chat_id"], "thumb_3_text", st.session_state['col3_fb']['text'])

    # update_db_entry(st.session_state["chat_id"], "scenario_rating", st.session_state['scenario_decision'])
    
    st.session_state.scenario_package = {
            'scenario': scenario,
            'answer set':  st.session_state['answer_set'],
            'judgment': st.session_state['scenario_decision'],
            'scenarios_all': scenario_dict,
            'chat_history': msgs,
            'adaptation_list': []
    }


def click_selection_no():
    """ Function called on_submit when a user clicks on 'actually, let me try another one'. 
     
    The only purpose is to set the scenario judged flag back on 
    """
    st.session_state['scenario_judged'] = True

def sliderChange(name, *args):
    """Function called on_change for the 'Judge_scenario' slider.  
    
    It updates two variables:
    st.session_state['scenario_judged'] -- which shows that some rating was provided by the user and un-disables a button for them to accept the scenario and continue 
    st.session_state['scenario_decision'] -- which stores the current rating

    """
    st.session_state['scenario_judged'] = False
    st.session_state['scenario_decision'] = st.session_state[name]


     
def scenario_selection (popover, button_num, scenario):
    """ Helper function which sets up the text & infrastructure for each scenario popover. 

    Arguments: 
    popover: streamlit popover object that we are operating on 
    button_num (str): allows us to keep track which scenario column the popover belongs to 
    scenario (str): the text of the scenario that the button refers to  
    """
    with popover:
        
        ## if this is the first run, set up the scenario_judged flag -- this will ensure that people cannot accept a scenario without rating it first (by being passes as the argument into 'disabled' option of the c1.button). For convenience and laziness, the bool is flipped -- "True" here means that 'to be judged'; "False" is 'has been judged'. 
        if "scenario_judged" not in st.session_state:
            st.session_state['scenario_judged'] = True


        st.markdown(f"How well does the scenario {button_num} capture what you had in mind?")
        sliderOptions = ["Not really ", "Needs some edits", "Pretty good but I'd like to tweak it", "Ready as is!"]
        slider_name = f'slider_{button_num}'

        scenario_rating = st.select_slider("Judge_scenario", label_visibility= 'hidden', key = slider_name, options = sliderOptions, on_change= sliderChange, args = (slider_name,))
        # update_db_entry(st.session_state["chat_id"], "scenario_rating", scenario_rating)
        # if scenario_rating == "Ready as is!":
            # update_db_entry(st.session_state["chat_id"], "final_scenario", scenario)
            
        

        c1, c2 = st.columns(2)
        
        ## the accept button should be disabled if no rating has been provided yet
        c1.button("Continue with this scenario 🎉", key = f'yeskey_{button_num}', on_click = click_selection_yes, args = (button_num, scenario), disabled = st.session_state['scenario_judged'])

        ## the second one needs to be accessible all the time!  
        c2.button("actually, let me try another one 🤨", key = f'nokey_{button_num}', on_click= click_selection_no)



def reviewData(testing):
    """ Procedure that governs the scenario review and selection by the user. 

    It presents the scenarios generated in previous phases (and saved to st.session_state) and sets up the feedback / selection buttons and popovers. 
    """

    ## If we're testing this function, the previous functions have set up the three column structure yet and we don't have scenarios. 
    ## --> we will set these up now. 
    if testing:
        testing_reviewSetUp() 


    ## if this is the first time running, let's make sure that the scenario selection variable is ready. 
    if 'scenario_selection' not in st.session_state:
        st.session_state['scenario_selection'] = '0'

    ## assuming no scenario has been selected 
    if st.session_state['scenario_selection'] == '0':
        # setting up space for the scenarios 
        col1, col2, col3 = st.columns(3)
        
        ## check if we had any feedback before:
        ## set up a dictionary:
        disable = {
            'col1_fb': None,
            'col2_fb': None,
            'col3_fb': None,
        }
        ## grab any answers we already have:
        for col in ['col1_fb','col2_fb','col3_fb']:
            if col in st.session_state and st.session_state[col] is not None:
                
                if DEBUG: 
                    st.write(col)
                    st.write("Feeedback 1:", st.session_state[col]['score'])
                
                # update the corresponding entry in the disable dict
                disable[col] = st.session_state[col]['score']

        # now set up the columns with each scenario & feedback functions
        with col1: 
            st.header("Scenario 1") 
            st.write(st.session_state.response_1['output_scenario'])
            col1_fb = streamlit_feedback(
                feedback_type="thumbs",
                optional_text_label="[Optional] Please provide an explanation",
                align='center',
                key="col1_fb",
                # this ensures that feedback cannot be submitted twice 
                disable_with_score = disable['col1_fb'],
                on_submit = collectFeedback,
                args = ('col1',
                        st.session_state.response_1['output_scenario']
                        )
            )

        with col2: 
            st.header("Scenario 2") 
            st.write(st.session_state.response_2['output_scenario'])
            col2_fb = streamlit_feedback(
                feedback_type="thumbs",
                optional_text_label="[Optional] Please provide an explanation",
                align='center',
                key="col2_fb",
                # this ensures that feedback cannot be submitted twice 
                disable_with_score = disable['col2_fb'],            
                on_submit = collectFeedback,
                args = ('col2', 
                        st.session_state.response_2['output_scenario']
                        )
            )        
        
        with col3: 
            st.header("Scenario 3") 
            st.write(st.session_state.response_3['output_scenario'])
            col3_fb = streamlit_feedback(
                feedback_type="thumbs",
                optional_text_label="[Optional] Please provide an explanation",
                align='center',
                key="col3_fb",
                # this ensures that feedback cannot be submitted twice 
                disable_with_score = disable['col3_fb'],            
                on_submit = collectFeedback,
                args = ('col3', 
                        st.session_state.response_3['output_scenario']
                        )
            )   


        ## now we should have col1, col2, col3 with text available -- let's set up the infrastructure for selection. 
        st.divider()

        if DEBUG:
            st.write("run ID", st.session_state['run_id'])
            if 'temp_debug' not in st.session_state:
                st.write("no debug found")
            else:
                st.write("debug feedback", st.session_state.temp_debug)
        


        ## if we haven't selected scenario, let's give them a choice. 
        st.chat_message("ai").write("Please have a look at the scenarios above. Use the 👍 and 👎  to leave a rating and short comment on each of the scenarios. Then pick the one that you like the most to continue. ")
     
        b1,b2,b3 = st.columns(3)
        # set up the popover buttons 
        p1 = b1.popover('Pick scenario 1', use_container_width=True)
        p2 = b2.popover('Pick scenario 2', use_container_width=True)
        p3 = b3.popover('Pick scenario 3', use_container_width=True)

        # and now initialise them properly
        scenario_selection(p1,'1', st.session_state.response_1['output_scenario']) 
        scenario_selection(p2,'2',st.session_state.response_2['output_scenario']) 
        scenario_selection(p3,'3',st.session_state.response_3['output_scenario']) 
    
    
    ## and finally, assuming we have selected a scenario, let's move into the final state!  Note that we ensured that the screen is free for any new content now as people had to click to select a scenario -- streamlit is starting with a fresh page 
    else:
        # great, we have a scenario selected, and all the key information is now in st.session_state['scenario_package'], created in the def click_selection_yes(button_num, scenario):

        # set the flow pointer accordingly 
        st.session_state['agentState'] = 'finalise'
        # print("ended loop -- should move to finalise!")
        finaliseScenario()


def updateFinalScenario (new_scenario):
    """ Updates the final scenario when the user accepts. 
    """
    st.session_state.scenario_package['scenario'] = new_scenario
    st.session_state.scenario_package['judgment'] = "Ready as is!"

def updateFinalScenario_textEdit (new_scenario):
    """ Updates the final scenario when the user accepts. 
    """
    ## save the adaptation step into the package: 
    st.session_state.scenario_package['adaptation_list'].append([f"direct_text_edit from: {st.session_state.scenario_package['scenario']}", new_scenario])
    
    st.session_state.scenario_package['scenario'] = new_scenario
    st.session_state.scenario_package['judgment'] = "Ready as is!"


@traceable
def finaliseScenario():
    """ Procedure governs the last part of the flow, which is the scenario adaptation.
    """

    # grab a 'local' copy of the package collected in the previous flow
    package = st.session_state['scenario_package']
    package['chat_id'] = st.session_state['chat_id']
    package['timestamp'] = st.session_state['timestamp']

    # if scenario is judged as 'ready' by the user -- we're done
    if package['judgment'] == "Ready as is!":
        st.markdown(":tada: Yay! :tada:")
        st.markdown("You've now completed the interaction and hopefully found a scenario that you liked! Your code for Prolific is '**CyberCorgi CodeCrumbs**.' Copy this now as you will need it to complete the survey.")
        st.markdown("")
        st.markdown("Please keep this window open until you complete the entire study. You may refer back to the scenario here at any point.")
        st.markdown("")
        st.markdown(f":green[{package['scenario']}]")
        
        package['chat_history'] = [(msg.type, msg.content) for msg in package['chat_history'].messages]
        table.put_item(
            Item=package
        )
            # st.session_state.scenario_package = {
                # 'scenario': scenario,    <- final scenario
                # 'answer set':  st.session_state['answer_set'],   <- the extracted data
                # 'judgment': st.session_state['scenario_decision'],  <-- 'ready as is' 
                # 'scenarios_all': scenario_dict,  <-- three original scenarios 
                # 'chat_history': msgs     <-- all of the initial chat_history 
                # 'adaptation_list': []   <-- list of adaptations made to the scenario 
            # }

        
            

        

    # if the user still wants to continue adapting
    else:
        # set up a streamlit container for the original scenario

        original = st.container()
        
        with original:
            st.markdown(f"It seems that you selected a story that you liked ... but that you also think it :red[{package['judgment']}]. You can either edit this below, or ask the AI to adapt it for you.)")

            st.divider()
            st.markdown("### Adapt yourself ✍️ :")
            new_scenario = st.text_area("Adapt your story directly", value=package['scenario'], height = 230, label_visibility="hidden")
            
            st.button("I'm happy with my edits", 
                      on_click=updateFinalScenario_textEdit,
                      args=(new_scenario,)
                      )
            st.markdown("\n")
        
        # set up a streamlit container for the new conversation & adapted scenario
        adapt_convo_container = st.container()
        
        with adapt_convo_container:
            st.divider()
            st.markdown("### Adapt with AI 🦾 :")
            st.chat_message("ai").write("Okay, what's missing or could change to make this better?")
        
            # once user enters something 
            if prompt:
                st.chat_message("human").write(prompt) 
                # append_list_entry(st.session_state["chat_id"], "editing_chat", {"role": "human", "content": prompt})

                # use a new chain, drawing on the prompt_adaptation template from lc_prompts.py
                adaptation_prompt = PromptTemplate(input_variables=["input", "scenario"], template = prompt_adaptation)
                json_parser = SimpleJsonOutputParser()

                chain = adaptation_prompt | chat | json_parser

                # set up a UX feedback in case the scenario takes longer to generate
                # note -- spinner disappears once the code inside finishes
                with st.spinner('Working on your updated scenario 🧐'):
                    new_response = chain.invoke({
                        'scenario': package['scenario'], 
                        'input': prompt
                        })
                    # st.write(new_response)

                st.markdown(f"Here is the adapted response: \n :orange[{new_response['new_scenario']}]\n\n **what do you think?**")
                # append_list_entry(st.session_state["chat_id"], "editing_chat", {"role": "assistant", "content": new_response['new_scenario']})
                
                ## save the adaptation step into the package: 
                st.session_state.scenario_package['adaptation_list'].append([prompt, new_response['new_scenario']])
               
              
                c1, c2  = st.columns(2)

                c1.button("All good!", 
                          on_click=updateFinalScenario,
                          args=(new_response['new_scenario'],))

                # clicking the "keep adapting" button will force streamlit to refresh the page 
                # --> this loop will run again.  
                c2.button("Keep adapting")


                ## TODO -- add an opportunity for people to rewrite the scenario themselves. 
                # The implementation below wasn't very aesthetically pleasing. 

                # popover_rewrite = c3.popover("I'll rewrite it myself")
                # with popover_rewrite:
                #     txt = st.text_area("Edit the scenario yourself and press command + Enter when you're happy with it",value=new_response['new_scenario'], on_change=test_area)            


            

def stateAgent(): 
    """ Main flow function of the whole interaction -- keeps track of the system state and calls the appropriate procedure on each streamlit refresh. 
    """

    # testing will ensure using dummy data (rather than user-data collection) to simplify development / testing of later parts of the flow. 
    testing = False

    # keep track of where we are, if testing
    if testing:
        print("Running stateAgent loop -- session state: ", st.session_state['agentState'])


    # Main loop -- selecting the right 'agent' each time: 
    if st.session_state['agentState'] == 'start':
            getData(testing)
            # summariseData(testing)
            # reviewData(testing)
    elif st.session_state['agentState'] == 'summarise':
            summariseData(testing)
    elif st.session_state['agentState'] == 'review':
            reviewData(testing)
    elif st.session_state['agentState'] == 'finalise':
            finaliseScenario()



def markConsent():
    """On_submit function that marks the consent progress 
    """
    st.session_state['consent'] = True

if 'pid' not in st.query_params:
    st.write("Sorry, there has been an error collecting your Prolific ID. Please contact the researcher for assistance.")
    st.stop()

### check we have consent -- if so, run normally 
if st.session_state['consent'] and 'pid' in st.query_params: 
    
    # setting up the right expanders for the start of the flow
    if st.session_state['agentState'] == 'review':
        st.session_state['exp_data'] = False

    entry_messages = st.expander("Collecting your story", expanded = st.session_state['exp_data'])

    if st.session_state['agentState'] == 'review':
        review_messages = st.expander("Review Scenarios")

    
    # create the user input object 
    prompt = st.chat_input()


    # Get an OpenAI API Key before continuing
    if "openai_api_key" in st.secrets:
        openai_api_key = st.secrets.openai_api_key
    else:
        openai_api_key = st.sidebar.text_input("OpenAI API Key", type="password")
    if not openai_api_key:
        st.info("Enter an OpenAI API Key to continue")
        st.stop()



    # Set up the LangChain for data collection, passing in Message History
    chat = ChatOpenAI(temperature=0.3, model=st.session_state.llm_model, openai_api_key = openai_api_key)

    prompt_updated = PromptTemplate(input_variables=["history", "input"], template = prompt_datacollection)

    conversation = ConversationChain(
        prompt = prompt_updated,
        llm = chat,
        verbose = True,
        memory = memory
        )
    
    # start the flow agent 
    stateAgent()

# we don't have consent yet -- ask for agreement and wait 
else: 
    print("don't have consent!")
    consent_message = st.container()
    with consent_message:
        st.markdown(''' 
                    ## Welcome to our story collection bot.

                    \n In this task you’re going to engage with a prototype chatbot that asks you to recall experiences using social media. 
                    
                    \n \n **It's important that you do not report situations that contain information that would allow someone to identify anyone in the story including yourself.** 
                    
                    \n \n To proceed to the task, please confirm that you have read and understood this information.
        ''')
        st.button("I accept", key = "consent_button", on_click=markConsent)
           


