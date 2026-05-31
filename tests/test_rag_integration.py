from agents.stage4_rag import TravelRAG


def test_data_directory_rag_retrieves_city_specific_content(tmp_path):
    docs = TravelRAG.default_knowledge()
    assert docs
    rag = TravelRAG(index_dir=str(tmp_path / "rag_idx"))
    rag.load_knowledge(docs)

    cases = [
        ("成都不吃辣", "成都"),
        ("北京三天 故宫", "北京"),
        ("三亚海滩", "三亚"),
    ]
    for query, keyword in cases:
        results = rag.search(query, top_k=10, rerank_top_k=3)
        context = rag.format_context(results)
        assert results
        assert keyword in context
