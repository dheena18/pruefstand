// Cases-panel rows of the ui-spec 14.2 matrix: a refused case and an `en` case (UI9-12, UI9-16).
import { EN_CASE, PASS_RUN, REFUSED_CASE } from "./fixture-ids";
import { row, run, type Row } from "./matrix";

const panel = (state: string, id: string, expect: Row["expect"]): Row =>
  row({
    page: "Cases list",
    state,
    set: "populated",
    fixtureRunId: PASS_RUN,
    path: `${run(PASS_RUN)}cases/?case=${id}`,
    expect: { hydrated: true, ...expect },
  });

export const caseRows: Row[] = [
  panel("refused case in the panel", REFUSED_CASE, { present: ["p.case-text"] }),
  // question and answers carry the case language (ui-spec 9): the only `lang="en"` text on a de page
  panel("en case in the panel", EN_CASE, { present: ['p.case-text[lang="en"]'] }),
];
