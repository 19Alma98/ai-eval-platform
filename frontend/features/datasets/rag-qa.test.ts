import assert from "node:assert/strict";
import { test } from "node:test";
import {
  chatHistoryLength,
  chatQuestionPreview,
  chatTurns,
  formatChatQuestion,
  isChatInput,
} from "./rag-qa";

const chatInput = {
  history: [
    { role: "user", content: "Do you have a Pro plan?" },
    { role: "assistant", content: "Yes, we offer a Pro plan." },
  ],
  question: "How much does it cost?",
};

test("detects chat-shaped input", () => {
  assert.equal(isChatInput(chatInput), true);
  assert.equal(isChatInput("plain question"), false);
  assert.equal(isChatInput({ history: [] }), false);
});

test("previews the last question with prior count", () => {
  assert.equal(chatQuestionPreview(chatInput), "How much does it cost?");
  assert.equal(chatHistoryLength(chatInput), 2);
  assert.equal(formatChatQuestion(chatInput), "[2 prior] How much does it cost?");
  assert.equal(formatChatQuestion({ history: [], question: "alone" }), "alone");
});

test("builds readable turns including the final question", () => {
  assert.deepEqual(chatTurns(chatInput), [
    { role: "user", content: "Do you have a Pro plan?" },
    { role: "assistant", content: "Yes, we offer a Pro plan." },
    { role: "user", content: "How much does it cost?" },
  ]);
});
