const ignores = require('./eslint.ignores.cjs');

module.exports = [{ignores}, ...require('gts')];
