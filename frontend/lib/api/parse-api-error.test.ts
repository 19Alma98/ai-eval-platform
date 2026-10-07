import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  ApiError,
  formatErrorForUi,
  parseApiErrorBody,
} from "./client";

describe("parseApiErrorBody", () => {
  it("extracts FastAPI string detail", () => {
    assert.equal(
      parseApiErrorBody(
        404,
        JSON.stringify({ detail: "Experiment not found: abc" }),
      ),
      "Experiment not found: abc",
    );
  });

  it("formats Pydantic 422 detail arrays", () => {
    const body = JSON.stringify({
      detail: [
        {
          type: "string_too_short",
          loc: ["body", "name"],
          msg: "String should have at least 1 character",
        },
        {
          type: "missing",
          loc: ["body", "dataset_id"],
          msg: "Field required",
        },
      ],
    });
    assert.equal(
      parseApiErrorBody(422, body),
      "name: String should have at least 1 character; dataset_id: Field required",
    );
  });

  it("uses friendly fallback for 500 JSON", () => {
    assert.equal(
      parseApiErrorBody(500, JSON.stringify({ detail: "Internal Server Error" })),
      "Something went wrong on the server. Try again.",
    );
  });

  it("uses friendly fallback for HTML bodies", () => {
    assert.equal(
      parseApiErrorBody(502, "<!DOCTYPE html><html><body>Bad Gateway</body></html>"),
      "Something went wrong on the server. Try again.",
    );
  });

  it("uses Not found for empty 404 body", () => {
    assert.equal(parseApiErrorBody(404, ""), "Not found.");
  });

  it("returns plain text bodies as-is", () => {
    assert.equal(parseApiErrorBody(400, "evaluator_ids must not be empty"), "evaluator_ids must not be empty");
  });
});

describe("formatErrorForUi", () => {
  it("returns ApiError message without status prefix", () => {
    assert.equal(
      formatErrorForUi(new ApiError(500, "Something went wrong on the server. Try again.")),
      "Something went wrong on the server. Try again.",
    );
  });

  it("maps network failures to a human message", () => {
    assert.equal(
      formatErrorForUi(new TypeError("Failed to fetch")),
      "Could not reach the API. Check that the backend is running.",
    );
  });

  it("returns Unknown error for non-Error values", () => {
    assert.equal(formatErrorForUi(null), "Unknown error");
  });
});
