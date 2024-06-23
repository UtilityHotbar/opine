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
import xmltodict


MAX_THREADS= 10
URL = 'https://caselaw.nationalarchives.gov.uk/judgments/search'
BASE_URL = 'https://caselaw.nationalarchives.gov.uk'


form = "%(asctime)s: %(message)s"

logging.basicConfig(format=form, level=logging.INFO, datefmt="%H:%M:%S")
client = anthropic.Anthropic()

def get_importance_of_case(url):
    prefix= url.split('/')[1].lower()
    if prefix == 'uwsc' or prefix == 'uwhl':
        return 1
    elif prefix == 'ewca':
        return 2
    elif prefix == 'ewhc':
        return 3
    else:
        return 4

def get_prefix(url):
    prefix= url.split('/')[1].lower()
    if prefix not in ['uwsc', 'uwhl','ewca','ewhc']:
        prefix = 'Other'
        return prefix
    else:
        return prefix.upper()

@st.cache_data
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
    text = st.text_input('Enter search terms')
    MAX_THREADS = st.number_input('Results to find (max 50): ', min_value=1, max_value=50, value=10)
    if text is not '':
        param_xml = get_response(f'Here is a user\'s search query for a UK legal database:\n<query>{text}</query>\nUse this query to fill out the following JSON fields. For example, if the user types "Crown" or "R." the party field should contain "r". The to_date_X and from_date_X fields contain the year, month, and day of the query. For example, "To 1st May 2020" should be to_date_0: 1, to_date_1: 5, to_date_2: 2020. Respond in this format:\n\n<format>\n<query>any query keywords</query>\n<judge>names of judges</judge>\n<party>names of any parties</party>\n<from_date_0>day to start searching (if not specified, do not fill in)</from_date_0><from_date_1>month to start searching (if not specified, do not fill in)</from_date_1><from_date_2>year to start searching (if not specified, do not fill in)</from_date_2>\n<to_date_0>day to stop searching (if not specified, do not fill in)</to_date_0><to_date_1>month to stop searching (if not specified, do not fill in)</to_date_1><to_date_2>year to start searching (if not specified, do not fill in)</to_date_2>\n</format>')
        logging.info(param_xml)
        try:
            param_xml = param_xml.split('<format>')[1].split('</format>')[0]
        except IndexError:
            param_xml = param_xml
        try:
            param_xml = '<xml>'+param_xml.replace('\n','')+'</xml>'
            logging.info(param_xml)
            PARAMS = json.dumps(xmltodict.parse(param_xml)).replace('null', '""')
            print('json_stringis', PARAMS)
            PARAMS = json.loads(PARAMS)['xml']
            print('dictis', PARAMS)

            PARAMS['order'] = 'relevance'
            PARAMS['page'] = '1'
            PARAMS['per_page'] = '50'
        except Exception as e:
            logging.warn(e)
            logging.warn('Degrading to dumb search')
            PARAMS = {'query':text,
                      'judge':'',
                      'party':'',
                      'order':'relevance','page':'1','per_page':'50'}

        r = requests.get(URL, params=PARAMS)
        soup = BeautifulSoup(r.text, 'html.parser')

        raw_links = soup.find_all("span",class_="judgment-listing__title" )
        links = []
        i = 0
        raw_html_dump = {}
        summaries = {}
        titles ={}
        master_threads= []
        for link in raw_links:
            links.append(link.find('a')['href'])
        links.sort(key=get_importance_of_case)

        links = links[:MAX_THREADS]
        st.write(f'Found {len(links)} hits.')

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
        with st.sidebar:
            st.write('## Cases')
            for link in links:
                x = st.write(f'[({get_prefix(link)}) {titles[link]}]({BASE_URL+"/"+link})')
                select_titles.append(titles[link])

        select_to_analyse = st.multiselect('Select cases to summarise', select_titles)

        logging.info('Showing results')
        if st.button('Generate Report'):
            summary_dump = {}
            selected_links = [links[select_titles.index(_)] for _ in select_to_analyse]
            selected_links.sort(key=get_importance_of_case)
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
