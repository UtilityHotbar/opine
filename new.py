import streamlit as st
import streamlit.components.v1 as components
import threading
import logging
import requests
from requests_html import HTMLSession
from bs4 import BeautifulSoup
import bs4
import anthropic
import time
import random
import os
import json



MAX_THREADS= 10
URL = 'https://caselaw.nationalarchives.gov.uk/judgments/search'
BASE_URL = 'https://caselaw.nationalarchives.gov.uk'


form = "%(asctime)s: %(message)s"

logging.basicConfig(format=form, level=logging.INFO, datefmt="%H:%M:%S")
client = anthropic.Anthropic()

def get_response(msg,  target=None, target_id=None, model="claude-3-5-sonnet-20240620", max_tokens=1000, temperature=0.5,):
    if type(msg) == str:
        messages =[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"{msg}"
                            }
                        ]
                    }
                ]
    elif type(msg) == list:
        messages = msg
    else:
        raise RuntimeError('Supply str or list of dicts as prompt for response getting')
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system="You are a clever legal assistant and analyst. When you are uncertain, you always say so. You are efficient and perfect in your responses.",
        messages=messages)
    result = '\n'.join([obj.text for obj in message.content])
    if target is None:
        return result
    else:
        target[target_id] = result


def get_template(prompt, article_html,rider=None):
        summary_template = [
                {'role': 'user', 'content': [
                    {'type': 'text', 'text': f'{prompt}'}
                    ]},
                {'role': 'assistant', 'content': [
                    {'type': 'text', 'text': 'Sure thing! I am an expert in this field.'}
                    ]},
                {'role': 'user', 'content': [
                    {'type': 'text', 'text': 'Here is the case'},
                    {'type': 'text', 'text': article_html}
                    ]}]
        if rider:
            summary_template[-1]['content'].append({'type': 'text', 'text': rider})
        return summary_template

def get_article_summary(url: str, summary_dump: dict, article_data: dict):
    logging.info('Starting summary of '+url)
    summary_dump[url] = get_response(get_template('Hi claude, I have a legal case as a block of html data here, can I get a one-paragraph summary of the spicy parts?', article_data[url], rider="Remember, I want a 1 paragraph summary! Answer with this format:\n<format>summary goes here</format>"))
    logging.info('Summary from '+url+' done')


def get_article_contents(url: str, raw_html_dump: dict,titles: dict):
    logging.info('starting request thread for: '+url)
    time.sleep(random.randint(1, 100)/100)
    r = requests.get(BASE_URL+'/'+url)
    soup = BeautifulSoup(r.text, 'html.parser')
    article_html = soup.find('article').text

    titles[url] = soup.find('h1').text
    # titles[url] = get_response(f'Claude, please get the contents of the JSON field "title" from this text: {titles[url]}. Return the contents of the JSON field "title" ONLY, with no other text.')
    logging.info(titles[url])
    raw_html_dump[url] = article_html
    logging.info('request for data from '+url+' done')


def main():
    st.write('# Opine Search')
    text = st.text_input('Enter search terms').replace(' ', '+')
    if text is not '':
        PARAMS = {'query':text,
            'judge':'',
            'party':'','order':'relevance','page':'1','per_page':'50'}
        r = requests.get(URL, params=PARAMS)
        soup = BeautifulSoup(r.text, 'html.parser')

        raw_links = soup.find_all("span",class_="judgment-listing__title" )
        links = []
        st.write(f'Found {len(raw_links)} hits.')
        i = 0
        raw_html_dump = {}
        summaries = {}
        titles ={}
        master_threads= []
        for link in raw_links:
            links.append(link.find('a')['href'])
        links = links[:MAX_THREADS]
        for link in links:
            i += 1
            if i > MAX_THREADS:
                logging.warning('Reached max request thread count')
                break
            x = threading.Thread(target=get_article_contents, args=(link,raw_html_dump,titles))
            master_threads.append(x)
        logging.info('Waiting for data...')
        for thread in master_threads:
            thread.start()

        for thread in master_threads:
            thread.join()
        # cleaned_link_db ={}
        # purged_links = purge_links(links,titles,cleaned_link_db)

        checkboxes = []
        select_titles = []
        for link in links:
            x = st.write(f'[{titles[link]}]({BASE_URL+"/"+link})')
            select_titles.append(titles[link])

        select_to_analyse = st.multiselect('Select cases to summarise', select_titles)

        logging.info('Showing results')
        if st.button('Generate Report'):
            summary_dump = {}
            selected_links = [links[select_titles.index(_)] for _ in select_to_analyse]
            threads = []
            for link in selected_links:
                s_thread = threading.Thread(target=get_article_summary, args=(link,summary_dump,raw_html_dump))
                threads.append(s_thread)
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            for l in summary_dump:
                summary_dump[l] = summary_dump[l].split('<format>')[1].split('</format>')[0]
                st.write(f'### Summary of [{titles[l]}]({BASE_URL+"/"+l}):')
                st.write(summary_dump[l])



if __name__ == '__main__':
    main()
