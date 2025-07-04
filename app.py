# -*- coding: utf-8 -*-
"""app.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1b-hAV2vBWvqpO6JNtVVhRFRDPdq8GqY5
"""

import pandas as pd
import numpy as np
import pickle
import os
from sentence_transformers import SentenceTransformer
import faiss
import re
import logging
from newspaper import Article
import gradio as gr
import nltk
import ast
from fuzzywuzzy import fuzz

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Download NLTK punkt_tab resource
try:
    nltk.download('punkt_tab', quiet=True)
except Exception as e:
    print(f"Warning: Failed to download punkt_tab. Error: {e}")

# Define test_type mappings
TEST_TYPE_MAP = {
    'A': 'Ability & Aptitude',
    'B': 'Biodata & Situational Judgement',
    'C': 'Competencies',
    'D': 'Development & 360',
    'E': 'Assessment Exercises',
    'K': 'Knowledge & Skills',
    'P': 'Personality & Behavior',
    'S': 'Simulations'
}

# Preprocessing functions
def clean_length(length_str):
    if pd.isna(length_str) or length_str == 'N/A':
        return 'Unknown duration'
    if 'Untimed' in length_str:
        return 'Untimed'
    if 'Variable' in length_str or 'variable' in length_str:
        import re
        max_val = re.search(r'max\s*(\d+)', length_str)
        if max_val:
            return f'Variable up to {max_val.group(1)} minutes'
        return 'Variable duration'
    import re
    num = re.search(r'\d+', length_str)
    if num:
        return f'Takes approximately {num.group()} minutes'
    return 'Unknown duration'

def extract_duration(length_str):
    if pd.isna(length_str) or length_str == 'N/A':
        return None
    if 'Untimed' in length_str or 'Variable' in length_str:
        return length_str
    import re
    match = re.search(r'(\d+)', length_str)
    if match:
        return int(match.group(1))
    return None

def expand_test_type(test_type):
    if pd.isna(test_type):
        return ''
    types = test_type.split()
    expanded = [f"{t} {TEST_TYPE_MAP.get(t, '')}" for t in types]
    return ', '.join(expanded)

def descriptive_boolean(field, yes_text, no_text):
    if pd.isna(field):
        return ''
    return yes_text if field.lower() == 'yes' else no_text

def process_languages(languages):
    if pd.isna(languages):
        return ''
    langs = [lang.strip() for lang in languages.split(',')]
    return f"Available in {', '.join(langs)}"

def process_levels(levels):
    if pd.isna(levels):
        return ''
    levels = [level.strip() for level in levels.split(',')]
    return f"Suitable for {', '.join(levels)}"

def chunk_description(description, max_chunks=3):
    if pd.isna(description):
        return ['']
    try:
        sentences = nltk.sent_tokenize(description)
    except LookupError as e:
        print(f"Warning: Sentence tokenization failed. Error: {e}")
        return [description]
    if len(sentences) <= max_chunks:
        return sentences
    chunk_size = max(1, len(sentences) // max_chunks)
    chunks = [' '.join(sentences[i:i + chunk_size]) for i in range(0, len(sentences), chunk_size)]
    return chunks[:max_chunks]

def normalize_name(name):
    if pd.isna(name) or not name:
        return ''
    name = str(name).lower().strip()
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name

# Load and preprocess data
def preprocess_data(file_path):
    df = pd.read_csv(file_path)
    df = df.dropna(subset=['name', 'description']).drop_duplicates(subset=['name'])
    df['length_clean'] = df['length'].apply(clean_length)
    df['duration_minutes'] = df['length'].apply(extract_duration)
    df['test_type_expanded'] = df['test_type'].apply(expand_test_type)
    df['remote_text'] = df['remote_testing'].apply(
        lambda x: descriptive_boolean(x, 'Supports remote testing', 'Does not support remote testing')
    )
    df['adaptive_text'] = df['adaptive_irt'].apply(
        lambda x: descriptive_boolean(x, 'Uses adaptive IRT', 'Does not use adaptive IRT')
    )
    df['language_text'] = df['language'].apply(process_languages)
    df['level_text'] = df['level'].apply(process_levels)
    model = SentenceTransformer('multi-qa-MiniLM-L6-cos-v1')
    df['combined_text'] = df.apply(
        lambda row: (
            f"SHL assessment {row['name']} {row['description']} {row['test_type_expanded']} "
            f"{row['remote_text']} {row['adaptive_text']} {row['language_text']} {row['level_text']} "
            f"{row['length_clean']} {row['name']} {row['description']}"
        ).strip(),
        axis=1
    )
    return df, model

# Generate embeddings
def generate_embeddings(df, model, embedding_file='assessment_embeddings.pkl'):
    if os.path.exists(embedding_file):
        print(f"Loading embeddings from {embedding_file}")
        with open(embedding_file, 'rb') as f:
            data = pickle.load(f)
        return data['embeddings'], data['metadata']
    print("Generating embeddings...")
    embeddings = []
    metadata = []
    for idx, row in df.iterrows():
        combined_text = row['combined_text']
        desc_chunks = chunk_description(row['description'])
        texts = [combined_text] + desc_chunks
        text_embeddings = model.encode(texts, show_progress_bar=False, batch_size=32)
        avg_embedding = np.mean(text_embeddings, axis=0)
        embeddings.append(avg_embedding)
        metadata.append({
            'index': idx,
            'name': row['name'],
            'url': row['url'],
            'test_type': row['test_type'],
            'remote_testing': row['remote_testing'],
            'adaptive_irt': row['adaptive_irt'],
            'language': row['language'],
            'level': row['level'],
            'length_clean': row['length_clean'],
            'duration_minutes': row['duration_minutes'],
            'description': row['description']
        })
    embeddings = np.array(embeddings, dtype=np.float32)
    data = {'embeddings': embeddings, 'metadata': metadata}
    with open(embedding_file, 'wb') as f:
        pickle.dump(data, f)
    print(f"Embeddings saved to {embedding_file}")
    return embeddings, metadata

# Load embeddings
def load_embeddings(embedding_file='assessment_embeddings.pkl'):
    logging.info(f"Loading embeddings from {embedding_file}")
    with open(embedding_file, 'rb') as f:
        data = pickle.load(f)
    embeddings = data['embeddings']
    if not isinstance(embeddings, np.ndarray):
        embeddings = np.array(embeddings, dtype=np.float32)
    metadata = data['metadata']
    embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
    for m in metadata:
        m['normalized_name'] = normalize_name(m['name'])
    return embeddings, metadata

# Parse list columns in benchmark_test.csv
def parse_list_column(col):
    if pd.isna(col) or not col:
        logging.warning(f"Empty column value: {col}")
        return []
    try:
        parsed = ast.literal_eval(col)
        if not isinstance(parsed, list):
            logging.warning(f"Parsed column is not a list: {col}")
            return []
        return [normalize_name(item) for item in parsed if item]
    except:
        logging.warning(f"Failed to parse column: {col}")
        return []

# Preprocess benchmark data
def load_benchmark(file_path='benchmark_test.csv'):
    logging.info(f"Loading benchmark data from {file_path}")
    df = pd.read_csv(file_path)
    df['assessments'] = df['assessments'].apply(parse_list_column)
    df['url'] = df['url'].apply(parse_list_column)
    return df

# Recommendation function
def recommend_assessments(query, index, metadata, model, top_k=5):
    logging.info(f"Processing query: {query[:50]}...")
    query_variations = [
        query,
        f"SHL assessment psychometric testing {query}",
        f"job assessment {query}"
    ]
    query_embeddings = model.encode(query_variations, show_progress_bar=False)
    query_embedding = np.mean(query_embeddings, axis=0)
    query_embedding = query_embedding / np.linalg.norm(query_embedding)
    distances, indices = index.search(np.array([query_embedding], dtype=np.float32), top_k)
    recommendations = []
    for idx, score in zip(indices[0], distances[0]):
        meta = metadata[idx]
        duration = f"{meta['duration_minutes']} minutes" if isinstance(meta['duration_minutes'], int) else meta['duration_minutes']
        recommendations.append({
            'name': meta['name'],
            'url': meta['url'],
            'test_type': meta['test_type'].split() if meta['test_type'] else [],
            'duration': duration,
            'remote_testing': meta['remote_testing'],
            'adaptive_irt': meta['adaptive_irt'],
            'normalized_name': meta['normalized_name'],
            'score': float(score)
        })
    return recommendations

# Extract job description from URL
def extract_job_description(url):
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text
    except Exception as e:
        logging.error(f"Failed to extract description from {url}: {e}")
        return None

# Evaluation metrics
def calculate_recall_at_k(predicted, relevant, k=3, fuzzy_threshold=70):
    predicted_k = predicted[:k]
    relevant_set = set(r for r in relevant if r)
    if not relevant_set:
        return 0
    hits = 0
    for pred in predicted_k:
        pred_name = pred['normalized_name']
        for rel in relevant_set:
            if (fuzz.ratio(pred_name, rel) >= fuzzy_threshold or
                pred_name in rel or rel in pred_name or
                any(word in rel for word in pred_name.split() if len(word) > 3)):
                hits += 1
                break
    return hits / len(relevant_set)

def calculate_ap_at_k(predicted, relevant, k=3, fuzzy_threshold=70):
    relevant_set = set(r for r in relevant if r)
    if not relevant_set:
        return 0
    score = 0
    num_hits = 0
    for i, pred in enumerate(predicted[:k], 1):
        pred_name = pred['normalized_name']
        for rel in relevant_set:
            if (fuzz.ratio(pred_name, rel) >= fuzzy_threshold or
                pred_name in rel or rel in pred_name or
                any(word in rel for word in pred_name.split() if len(word) > 3)):
                num_hits += 1
                score += num_hits / i
                break
    return score / min(len(relevant_set), k)

# Evaluate on benchmark
def evaluate_recommendations(benchmark_df, index, metadata, model): # Changed 'embeddings' to 'index'
    recall_scores = []
    ap_scores = []
    for idx, row in benchmark_df.iterrows():
        query = row['query']
        relevant_assessments = row['assessments']
        logging.info(f"Query {idx}: {query[:50]}...")
        logging.info(f"Relevant assessments: {relevant_assessments}")
        recommendations = recommend_assessments(query, index, metadata, model, top_k=10) # Changed 'embeddings' to 'index'
        predicted_names = [r['normalized_name'] for r in recommendations]
        logging.info(f"Predicted assessments: {predicted_names}")
        match_details = []
        for pred in recommendations[:3]:
            pred_name = pred['normalized_name']
            for rel in relevant_assessments:
                fuzzy_score = fuzz.ratio(pred_name, rel)
                partial = pred_name in rel or rel in pred_name
                keyword = any(word in rel for word in pred_name.split() if len(word) > 3)
                match_details.append({
                    'Predicted': pred_name,
                    'Relevant': rel,
                    'Fuzzy Score': fuzzy_score,
                    'Partial Match': partial,
                    'Keyword Match': keyword
                })
        logging.info(f"Match details: {match_details}")
        recall = calculate_recall_at_k(recommendations, relevant_assessments, k=3)
        ap = calculate_ap_at_k(recommendations, relevant_assessments, k=3)
        logging.info(f"Query {idx} - Recall@3: {recall:.4f}, AP@3: {ap:.4f}")
        if recall > 0:
            logging.info(f"Matches found: {[r['normalized_name'] for r in recommendations[:3] if any(fuzz.ratio(r['normalized_name'], rel) >= 70 or r['normalized_name'] in rel or rel in r['normalized_name'] or any(word in rel for word in r['normalized_name'].split() if len(word) > 3) for rel in relevant_assessments)]}")
        recall_scores.append(recall)
        ap_scores.append(ap)
    mean_recall_at_3 = np.mean(recall_scores)
    map_at_3 = np.mean(ap_scores)
    return mean_recall_at_3, map_at_3

# Manual testing function
def test_single_query(query, relevant_assessments, embeddings, metadata, model, top_k=5):
    recommendations = recommend_assessments(query, embeddings, metadata, model, top_k=top_k)
    recall = calculate_recall_at_k(recommendations, relevant_assessments, k=3)
    ap = calculate_ap_at_k(recommendations, relevant_assessments, k=3)
    result = []
    for r in recommendations:
        match_scores = [(rel, fuzz.ratio(r['normalized_name'], rel), r['normalized_name'] in rel or rel in r['normalized_name'])
                        for rel in relevant_assessments]
        result.append({
            'Name': r['name'],
            'Normalized Name': r['normalized_name'],
            'Score': r['score'],
            'URL': r['url'],
            'Test Type': ', '.join(r['test_type']),
            'Match Scores': str(match_scores)
        })
    return pd.DataFrame(result), relevant_assessments, recall, ap

if __name__ == "__main__":
    embedding_file = 'assessment_embeddings.pkl'
    if not os.path.exists(embedding_file):
        print("Preprocessing data and generating embeddings...")
        df, model = preprocess_data('shl_assessments.csv')
        embeddings, metadata = generate_embeddings(df, model, embedding_file)
    else:
        embeddings, metadata = load_embeddings(embedding_file)
        model = SentenceTransformer('multi-qa-MiniLM-L6-cos-v1')

    # Build FAISS index
    d = embeddings.shape[1]
    index = faiss.IndexFlatIP(d)  # Create the Faiss index
    index.add(embeddings)         # Add the embeddings to the index

    # Run evaluation if benchmark file exists
    benchmark_file = 'benchmark_test.csv'
    if os.path.exists(benchmark_file):
        print("Running evaluation...")
        benchmark_df = load_benchmark(benchmark_file)

        # Pass the Faiss index object to evaluate_recommendations
        mean_recall_at_3, map_at_3 = evaluate_recommendations(benchmark_df, index, metadata, model)

        print(f"Mean Recall@3: {mean_recall_at_3:.4f}")
        print(f"MAP@3: {map_at_3:.4f}")
        with open('evaluation_results.txt', 'w') as f:
            f.write(f"Mean Recall@3: {mean_recall_at_3:.4f}\n")
            f.write(f"MAP@3: {map_at_3:.4f}\n")

    # Define Gradio function
    def recommend_from_input(description, url):
        if description and url:
            return pd.DataFrame({"Message": ["Please provide either a job description or a job URL, not both."]})
        elif not description and not url:
            return pd.DataFrame({"Message": ["Please provide a job description or a job URL."]})
        elif url:
            query = extract_job_description(url)
            if query is None:
                return pd.DataFrame({"Message": ["Failed to extract job description from the provided URL."]})
        else:
            query = description

        recommendations = recommend_assessments(query, index, metadata, model, top_k=5)
        display_data = []
        for r in recommendations:
            url_html = f'<a href="{r["url"]}" target="_blank">{r["url"]}</a>'
            display_data.append({
                'Assessment Name': r['name'],
                'URL': r['url'],
                'Test Type': ', '.join(r['test_type']),
                'Duration': r['duration'],
                'Remote Testing': r['remote_testing'],
                'Adaptive IRT': r['adaptive_irt']
            })
        df = pd.DataFrame(display_data)
        return df

    # Launch Gradio interface
    iface = gr.Interface(
        fn=recommend_from_input,
        inputs=[gr.Textbox(label="Job Description", placeholder="Enter the job description here..."),
                gr.Textbox(label="Job URL", placeholder="Enter the job posting URL here...")],
        outputs=gr.Dataframe(),
        title="SHL Assessment Recommender",
        description="Enter a job description or a job URL to get recommended SHL assessments."
    )
    iface.launch()