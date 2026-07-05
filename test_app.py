import unittest
import os
import json
from unittest.mock import patch

import database
import detector
from app import app

class TestProvenanceGuard(unittest.TestCase):

    def setUp(self):
        # Configure a test database file and initialize it
        self.db_path = "test_provenance.db"
        database.DATABASE_NAME = self.db_path
        database.init_db(self.db_path)
        
        # Configure the Flask app test client
        self.client = app.test_client()
        self.client.testing = True

    def tearDown(self):
        # Close connection and cleanup test database file
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        if os.path.exists("logs/audit.jsonl"):
            try:
                os.remove("logs/audit.jsonl")
            except OSError:
                pass

    def test_heuristics_human(self):
        # Text with varied sentence lengths (High SLV)
        human_text = (
            "This is a sentence. "
            "But this is a much longer and more complex sentence containing multiple adjectives and verbs. "
            "Wait! "
            "Yes, variance should be high."
        )
        slv = detector.calculate_slv(human_text)
        ttr = detector.calculate_ttr(human_text)
        self.assertGreater(slv, 20.0)
        self.assertLess(ttr, 1.0)
        self.assertGreater(ttr, 0.5)

    def test_heuristics_ai_uniformity(self):
        # Text with identical sentence lengths (Low SLV)
        ai_text = (
            "We write short lines here. "
            "They all have five words. "
            "This sentence has five words. "
        )
        slv = detector.calculate_slv(ai_text)
        self.assertEqual(slv, 0.0)

    @patch('detector.get_llm_score')
    def test_submit_endpoint_human(self, mock_llm_score):
        # Mock LLM score as highly human (0.1)
        mock_llm_score.return_value = 0.1
        
        payload = {
            "author_id": "author_1",
            "title": "A Walk in the Woods",
            "content": (
                "Yesterday, I decided to wander through the ancient woods near my home. "
                "The air was crisp and scented with pine. "
                "I saw a deer. It was beautiful. "
                "As the sun dipped below the trees, casting long shadows across the path, I realized how quiet the world could be."
            )
        }
        
        response = self.client.post('/submit', json=payload)
        self.assertEqual(response.status_code, 201)
        
        data = json.loads(response.data)
        self.assertIn("submission_id", data)
        self.assertEqual(data["classification"], "human")
        self.assertLess(data["confidence_score"], 0.40)
        self.assertEqual(data["status"], "active")
        
        # Verify database record exists
        record = database.get_submission(data["submission_id"], db_path=self.db_path)
        self.assertIsNotNone(record)
        self.assertEqual(record["author_id"], "author_1")
        self.assertEqual(record["classification"], "human")

    @patch('detector.get_llm_score')
    def test_submit_endpoint_ai(self, mock_llm_score):
        # Mock LLM score as highly AI (0.95)
        mock_llm_score.return_value = 0.95
        
        payload = {
            "author_id": "author_2",
            "title": "AI Essay",
            "content": (
                "Furthermore, it is important to delve into the multifaceted tapestry of human evolution. "
                "Consequently, navigating this paradigm serves as a crucial testament to progress. "
                "Additionally, the integration of structured methodologies underscores our holistic trajectory."
            )
        }
        
        response = self.client.post('/submit', json=payload)
        self.assertEqual(response.status_code, 201)
        
        data = json.loads(response.data)
        self.assertEqual(data["classification"], "ai")
        self.assertGreater(data["confidence_score"], 0.80)
        self.assertEqual(data["status"], "active")

    @patch('detector.get_llm_score')
    def test_appeal_workflow(self, mock_llm_score):
        mock_llm_score.return_value = 0.9  # Flags as AI
        
        payload = {
            "author_id": "author_3",
            "title": "My Story",
            "content": "To write effectively, one must delve into the tapestry of human existence."
        }
        
        # Submit
        res_submit = self.client.post('/submit', json=payload)
        sub_id = json.loads(res_submit.data)["submission_id"]
        
        # Check initial status
        record = database.get_submission(sub_id, db_path=self.db_path)
        self.assertEqual(record["status"], "active")
        self.assertIsNone(record["appeal_reason"])
        
        # Appeal
        appeal_payload = {
            "submission_id": sub_id,
            "reason": "This is original work from my high school paper."
        }
        res_appeal = self.client.post('/appeal', json=appeal_payload)
        self.assertEqual(res_appeal.status_code, 200)
        
        appeal_data = json.loads(res_appeal.data)
        self.assertEqual(appeal_data["status"], "under_review")
        
        # Check updated status
        updated_record = database.get_submission(sub_id, db_path=self.db_path)
        self.assertEqual(updated_record["status"], "under_review")
        self.assertEqual(updated_record["appeal_reason"], "This is original work from my high school paper.")

    def test_appeal_nonexistent(self):
        appeal_payload = {
            "submission_id": "sub_missing99",
            "reason": "It's mine."
        }
        response = self.client.post('/appeal', json=appeal_payload)
        self.assertEqual(response.status_code, 404)

    @patch('detector.get_llm_score')
    def test_logs_endpoint(self, mock_llm_score):
        mock_llm_score.return_value = 0.5
        
        # Submit two entries
        self.client.post('/submit', json={"author_id": "a", "title": "t1", "content": "Hello world from a human author."})
        self.client.post('/submit', json={"author_id": "b", "title": "t2", "content": "Another short sentence goes here."})
        
        response = self.client.get('/logs')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(len(data["logs"]), 2)

if __name__ == '__main__':
    unittest.main()
