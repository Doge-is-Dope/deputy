// The runtime's user: reads and writes its own database, and nothing else.
db.getSiblingDB("computer_use").createUser({
  user: "runtime",
  pwd: process.env.MONGO_RUNTIME_PASSWORD,
  roles: [{ role: "readWrite", db: "computer_use" }],
});
