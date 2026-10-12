import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { resolveStaticExportParam } from "./static-export-params";

const EXPERIMENT_SEGMENT = /^\/experiments\/([^/]+)/;

describe("resolveStaticExportParam", () => {
  it("keeps a real useParams value", () => {
    assert.equal(
      resolveStaticExportParam(
        "50af5c63-0741-42cd-9a43-e436efa9391c",
        "/experiments/_/",
        EXPERIMENT_SEGMENT,
      ),
      "50af5c63-0741-42cd-9a43-e436efa9391c",
    );
  });

  it("reads the real id from the pathname when params are the export placeholder", () => {
    assert.equal(
      resolveStaticExportParam(
        "_",
        "/experiments/50af5c63-0741-42cd-9a43-e436efa9391c/",
        EXPERIMENT_SEGMENT,
      ),
      "50af5c63-0741-42cd-9a43-e436efa9391c",
    );
  });

  it("returns empty when both params and path are the placeholder", () => {
    assert.equal(
      resolveStaticExportParam("_", "/experiments/_/", EXPERIMENT_SEGMENT),
      "",
    );
  });

  it("returns empty when the param is missing and the path has no segment", () => {
    assert.equal(
      resolveStaticExportParam(undefined, "/experiments/", EXPERIMENT_SEGMENT),
      "",
    );
  });
});
