import datetime
import os
import time
import requests
from lxml import etree
from dateutil import relativedelta

HEADERS = {'Authorization': 'bearer ' + os.environ['ACCESS_TOKEN']}
USER_NAME = os.environ.get('USER_NAME', 'tanish35')
BIRTHDAY = datetime.date(2005, 12, 29)
API_CALLS = 0


def graphql(query, variables=None, max_retries=5):
    global API_CALLS
    for attempt in range(max_retries):
        API_CALLS += 1
        response = requests.post(
            'https://api.github.com/graphql',
            json={'query': query, 'variables': variables or {}},
            headers=HEADERS,
            timeout=30,
        )
        if response.status_code == 200:
            body = response.json()
            if 'errors' in body:
                raise Exception('GraphQL errors:', body['errors'])
            return body['data']
        if response.status_code in (502, 503, 504) and attempt < max_retries - 1:
            time.sleep(min(2 ** attempt, 8))
            continue
        raise Exception('GraphQL failed', response.status_code, response.text)


def daily_readme(birthday):
    diff = relativedelta.relativedelta(datetime.date.today(), birthday)
    return '{} year{}, {} month{}, {} day{}{}'.format(
        diff.years, 's' if diff.years != 1 else '',
        diff.months, 's' if diff.months != 1 else '',
        diff.days, 's' if diff.days != 1 else '',
        ' 🎂' if diff.months == 0 and diff.days == 0 else '')


def user_getter(username):
    data = graphql(
        'query($login: String!) { user(login: $login) { id } }',
        {'login': username},
    )
    return data['user']['id']


def follower_getter(username):
    data = graphql(
        '''query($login: String!) {
            user(login: $login) { followers { totalCount } }
        }''',
        {'login': username},
    )
    return data['user']['followers']['totalCount']


def graph_repos_stars(count_type, owner_affiliation):
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges {
                    node {
                        stargazers { totalCount }
                    }
                }
                pageInfo { endCursor hasNextPage }
            }
        }
    }'''
    cursor = None
    total_stars = 0
    total_count = None
    while True:
        data = graphql(query, {
            'owner_affiliation': owner_affiliation,
            'login': USER_NAME,
            'cursor': cursor,
        })
        repos = data['user']['repositories']
        if total_count is None:
            total_count = repos['totalCount']
        if count_type == 'repos':
            return total_count
        for edge in repos['edges']:
            total_stars += edge['node']['stargazers']['totalCount']
        if not repos['pageInfo']['hasNextPage']:
            return total_stars
        cursor = repos['pageInfo']['endCursor']


def commit_counter(author_id, owner_affiliation):
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $authorId: ID!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                edges {
                    node {
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    history(author: {id: $authorId}) {
                                        totalCount
                                    }
                                }
                            }
                        }
                    }
                }
                pageInfo { endCursor hasNextPage }
            }
        }
    }'''
    cursor = None
    total = 0
    while True:
        data = graphql(query, {
            'owner_affiliation': owner_affiliation,
            'login': USER_NAME,
            'authorId': author_id,
            'cursor': cursor,
        })
        repos = data['user']['repositories']
        for edge in repos['edges']:
            ref = edge['node']['defaultBranchRef']
            if ref and ref['target'] and ref['target']['history']:
                total += ref['target']['history']['totalCount']
        if not repos['pageInfo']['hasNextPage']:
            return total
        cursor = repos['pageInfo']['endCursor']


def svg_overwrite(filename, age_data, commit_data, star_data, repo_data, contrib_data, follower_data):
    tree = etree.parse(filename)
    root = tree.getroot()
    justify_format(root, 'age_data', age_data, 50)
    justify_format(root, 'commit_data', commit_data, 22)
    justify_format(root, 'star_data', star_data, 14)
    justify_format(root, 'repo_data', repo_data, 6)
    justify_format(root, 'contrib_data', contrib_data)
    justify_format(root, 'follower_data', follower_data, 10)
    tree.write(filename, encoding='utf-8', xml_declaration=True)


def justify_format(root, element_id, new_text, length=0):
    if isinstance(new_text, int):
        new_text = f"{'{:,}'.format(new_text)}"
    new_text = str(new_text)
    find_and_replace(root, element_id, new_text)
    just_len = max(0, length - len(new_text))
    if just_len <= 2:
        dot_string = {0: '', 1: ' ', 2: '. '}[just_len]
    else:
        dot_string = ' ' + ('.' * just_len) + ' '
    find_and_replace(root, f'{element_id}_dots', dot_string)


def find_and_replace(root, element_id, new_text):
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = new_text


def timed(label, fn, *args):
    start = time.perf_counter()
    result = fn(*args)
    elapsed = time.perf_counter() - start
    unit = f'{elapsed:.4f} s ' if elapsed > 1 else f'{elapsed * 1000:.4f} ms'
    print(f'   {label + ":":<21}{unit:>12}')
    return result, elapsed


if __name__ == '__main__':
    print('Calculation times:')
    owner_id, t_user = timed('account data', user_getter, USER_NAME)
    age_data, t_age = timed('age calculation', daily_readme, BIRTHDAY)
    commit_data, t_commit = timed(
        'commits',
        commit_counter,
        owner_id,
        ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'],
    )
    star_data, t_star = timed('stars', graph_repos_stars, 'stars', ['OWNER'])
    repo_data, t_repo = timed('repos', graph_repos_stars, 'repos', ['OWNER'])
    contrib_data, t_contrib = timed(
        'contributed',
        graph_repos_stars,
        'repos',
        ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'],
    )
    follower_data, t_follow = timed('followers', follower_getter, USER_NAME)

    svg_overwrite(
        'dark_mode.svg',
        age_data,
        commit_data,
        star_data,
        repo_data,
        contrib_data,
        follower_data,
    )

    total = t_user + t_age + t_commit + t_star + t_repo + t_contrib + t_follow
    print(f'Total function time: {total:.4f} s')
    print(f'Total GitHub GraphQL API calls: {API_CALLS}')
