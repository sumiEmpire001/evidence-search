import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from evidence_search import Index


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "index.db"
        self.index = Index(self.path)

    def test_ingest_search_and_exact_locations(self):
        self.index.add("guide", "Alpha\nBeta storage\nGamma storage\nDelta\n", lines_per_chunk=2)
        results = self.index.search("beta storage")
        self.assertEqual(len(results), 1)
        self.assertEqual((results[0]["first_line"], results[0]["last_line"]), (1, 2))
        self.assertEqual(results[0]["text"], "Alpha\nBeta storage\n")
        self.assertTrue(self.index.verify(results[0]["citation"], results[0]["text"]))

    def test_revision_replacement_invalidates_old_citations(self):
        self.index.add("guide", "Original queue")
        hit = self.index.search("queue")[0]
        self.index.add("guide", "Replacement storage")
        self.assertFalse(self.index.verify(hit["citation"], hit["text"]))
        self.assertEqual(self.index.search("queue"), [])
        self.assertEqual(len(self.index.search("storage")), 1)

    def test_delete_removes_documents_chunks_and_search_results(self):
        self.index.add("private", "Private sensor record")
        hit = self.index.search("sensor")[0]
        self.assertTrue(self.index.delete("private"))
        self.assertFalse(self.index.delete("private"))
        self.assertEqual(self.index.documents(), [])
        self.assertEqual(self.index.search("sensor"), [])
        self.assertFalse(self.index.verify(hit["citation"], hit["text"]))

    def test_duplicates_and_restart_do_not_duplicate_results(self):
        self.index.add("guide", "Durable queue")
        self.index.add("guide", "Durable queue")
        again = Index(self.path)
        self.assertEqual(len(again.search("durable")), 1)

    def test_empty_query_and_unsupported_answer(self):
        self.assertEqual(self.index.search('" - ()'), [])
        self.assertFalse(self.index.answer("nonexistent")["supported"])
        self.assertEqual(self.index.answer("nonexistent")["excerpts"], [])

    def test_queries_are_tokens_not_fts_programs(self):
        self.index.add("one", "alpha beta")
        self.assertEqual(self.index.search('alpha OR "broken'), [])
        self.assertEqual(len(self.index.search('alpha "beta')), 1)

    def test_all_any_and_result_limit(self):
        self.index.add("one", "alpha beta")
        self.index.add("two", "alpha gamma")
        self.assertEqual(len(self.index.search("alpha beta")), 1)
        self.assertEqual(len(self.index.search("beta gamma", mode="any")), 2)
        self.assertEqual(len(self.index.search("alpha", limit=1)), 1)

    def test_invalid_ingestion_preserves_previous_version(self):
        self.index.add("one", "Valid content")
        for text in ("", "  ", "bad\x00text", "x" * (2 * 1024 * 1024 + 1)):
            with self.assertRaises(ValueError):
                self.index.add("one", text)
        self.assertEqual(len(self.index.search("valid")), 1)

    def test_verification_rejects_wrong_source_or_fabricated_quote(self):
        self.index.add("one", "Solar sensors measure light")
        hit = self.index.search("solar")[0]
        self.assertFalse(self.index.verify(hit["citation"], "Solar sensors measure money"))
        self.assertFalse(self.index.verify(hit["citation"].replace("one@", "two@"), hit["text"]))
        self.assertFalse(self.index.verify(hit["citation"], ""))

    def test_unicode_and_line_endings_are_normalized(self):
        self.index.add("unicode", "Café monitor\r\nVoltage rising\rDone", lines_per_chunk=1)
        hit = self.index.search("café")[0]
        self.assertEqual(hit["text"], "Café monitor\n")
        self.assertEqual(hit["last_line"], 1)

    def test_file_ingestion_rejects_binary_formats(self):
        file = Path(self.temp.name) / "guide.md"
        file.write_text("Sensor manual", encoding="utf-8")
        self.index.add_file("guide", file)
        self.assertEqual(len(self.index.search("sensor")), 1)
        with self.assertRaises(ValueError):
            self.index.add_file("other", file.with_suffix(".pdf"))

    def test_evaluation_checks_retrieval_and_citations(self):
        self.index.add("queue", "Workers renew queue leases")
        self.index.add("sensor", "Temperature sensors report readings")
        report = self.index.evaluate([{"query": "leases", "expected": ["queue"]}, {"query": "readings", "expected": ["sensor"]}, {"query": "bananas", "expected": []}])
        self.assertEqual(report["pass_rate"], 1)
        self.assertTrue(report["citations_valid"])

    def test_concurrent_updates_leave_one_consistent_revision(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda n: self.index.add("same", "Sensor version " + str(n)), range(12)))
        hits = self.index.search("sensor")
        self.assertEqual(len(hits), 1)
        self.assertTrue(self.index.verify(hits[0]["citation"], hits[0]["text"]))

    def test_validation_and_deterministic_ranking(self):
        for document_id in ("../bad", "", "x" * 81):
            with self.assertRaises(ValueError):
                self.index.add(document_id, "text")
        with self.assertRaises(ValueError):
            self.index.search("text", limit=0)
        self.index.add("b", "queue")
        self.index.add("a", "queue")
        self.assertEqual([r["document_id"] for r in self.index.search("queue")], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
