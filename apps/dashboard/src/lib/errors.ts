/** Typed errors of the data layer (ui-spec §4.8): the error boundary shows the class, never a stack trace. */
export class DashboardDataError extends Error {
  readonly file: string;

  constructor(message: string, file: string) {
    super(message);
    this.file = file;
    this.name = new.target.name;
  }
}

/** A file carries a `schema_version` this build does not know. */
export class UnsupportedSchemaError extends DashboardDataError {}

/** A file the page needs is not in the data tree. */
export class NotFoundError extends DashboardDataError {}

/** A file does not match its JSON Schema (or is not JSON). */
export class ValidationError extends DashboardDataError {}
