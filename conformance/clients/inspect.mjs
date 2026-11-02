// Stdin CLI for the compatibility reader. Import javascript.mjs as the library.
import { readFileSync } from "node:fs";
import { strictParse } from "./canonical.mjs";
import { inspect } from "./javascript.mjs";

const request = strictParse(readFileSync(0));
console.log(JSON.stringify(request.cases.map(inspect)));
