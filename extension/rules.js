// The decision described in rules.md (bid, manual check or skip) and the "not software work" filter.
// Ports of rules.py and relevance.py. The three word lists are generated from relevance.py, so the
// two versions match exactly: rebuild them from there rather than editing them here.

export const BID = 'bid';
export const MANUAL = 'manual check';
export const SKIP = 'skip';
const SPEND_LIMIT = 100000;
const HIGH_RATE = 20.0;
const LOW_RATE = 10.0;

// '$301701' or '$2 037 596' -> 301701; null when there is no figure
export function amount(text) {
  if (!text) return null;
  const digits = String(text).replace(/[^\d.]/g, '');
  if (!digits) return null;
  const value = Number(digits);
  return Number.isNaN(value) ? null : value;
}

// [result, why] for one client block
export function decide(client) {
  client = client || {};
  const spent = amount(client['total spent']);
  const rate = amount(client['avg hourly rate']);
  const money = (n) => n.toFixed(0);
  if (spent === null && rate === null) return [BID, 'new client: Vollna shows no spend and no hourly rate'];
  if (spent === null || rate === null) {
    return [MANUAL, `half-missing figures: spend=${client['total spent'] ?? 'None'}, rate=${client['avg hourly rate'] ?? 'None'}`];
  }
  if (spent >= SPEND_LIMIT) {
    if (rate >= HIGH_RATE) return [BID, `spent $${money(spent)} (>= $100K) and pays $${rate.toFixed(2)}/hr (>= $20)`];
    return [MANUAL, `spent $${money(spent)} (>= $100K) but pays $${rate.toFixed(2)}/hr (< $20)`];
  }
  if (rate <= LOW_RATE) return [SKIP, `spent $${money(spent)} (< $100K) and pays $${rate.toFixed(2)}/hr (<= $10)`];
  return [MANUAL, `spent $${money(spent)} (< $100K) and pays $${rate.toFixed(2)}/hr (> $10)`];
}

// generated from relevance.py
const TECH = new RegExp("software|develop|programm|\\bcod(e|er|ers|ing)\\b|engineer|\\bapi\\b|\\bapis\\b|\\bapps?\\b|application|website|web site|\\bweb\\b|landing page|frontend|front-end|backend|back-end|full[- ]?stack|devops|\\bcloud\\b|\\baws\\b|azure|\\bgcp\\b|database|\\bsql\\b|mongo|postgres|mysql|firebase|supabase|python|javascript|typescript|\\bjava\\b|node\\.?js|react|\\bvue\\b|angular|next\\.?js|\\bphp\\b|laravel|django|flask|ruby|rails|golang|\\brust\\b|c\\+\\+|c#|\\.net\\b|\\bswift\\b|kotlin|flutter|android|\\bios\\b|saas|\\bcrm\\b|\\berp\\b|integrat|automat|script|\\bbots?\\b|chatbot|scrap(e|er|ing)|crawl|n8n|zapier|make\\.com|airtable|bubble|webflow|wordpress|shopify|\\bwix\\b|squarespace|plugin|extension|\\bhtml|\\bcss\\b|\\bui\\b|\\bux\\b|figma|dashboard|machine learning|\\bml\\b|\\bai\\b|\\bllm|gpt|openai|claude|gemini|agent dev|algorithm|blockchain|smart contract|solidity|web3|\\bgame\\b|\\bunity\\b|unreal|embedded|firmware|microcontroller|arduino|raspberry|\\biot\\b|electronic|\\bpcb\\b|fpga|verilog|vhdl|linux|docker|kubernetes|cyber|security|penetration|it support|excel|\\bvba\\b|google sheets|apps script|\\bqa\\b|hosting|\\bdns\\b|\\bseo\\b|twilio|stripe|dialer|voip|\\bcad\\b|matlab|\\bgis\\b|data scien|data analy|data engineer|data architect|computer vision|tech stack|github|deploy", 'i');
const CODE = new RegExp("\\bsoftware (developer|engineer|development)|\\bdeveloper\\b|\\bprogramm(er|ing)\\b|source code|codebase|\\bapi\\b|\\bapis\\b|\\bsdk\\b|github|gitlab|\\bpython\\b|javascript|typescript|\\bjava\\b|node\\.?js|\\breact\\b|\\bvue\\b|angular|next\\.?js|\\bphp\\b|laravel|django|flask|ruby on rails|golang|\\brust\\b|c\\+\\+|c#|\\.net\\b|\\bswift\\b|kotlin|flutter|\\bsql\\b|postgres|mysql|mongodb|firebase|supabase|\\baws\\b|docker|kubernetes|\\bhtml\\b|\\bcss\\b|wordpress|shopify (app|theme|develop)|webhook|\\bjson\\b|backend|back-end|frontend|front-end|full[- ]?stack|firmware|embedded|microcontroller|verilog|n8n|zapier|make\\.com|apps script|\\bvba\\b|\\b(build|create|make|develop|set up)\\b[^.|\\n]{0,40}?\\b(apps?|application|website|tool|platform|dashboard|bot|integration|plugin|extension|calculator|portal|system|software|script|database|crm)\\b|\\b(develop|code|program|script|automate) (a|an|the|our|my)\\b", 'i');
const OTHER = new RegExp("bookkeep|accounting|accountant|\\btax\\b|payroll|quickbooks|\\bxero\\b|\\baudit\\b|\\bcpa\\b|copywrit|ghostwrit|proofread|translat|transcri|subtitl|voice[- ]?over|voice act|narrat|\\bsales\\b|closer|cold call|telemarket|appointment setting|lead generation|recruit|virtual assistant|executive assistant|executive support|customer service|customer support|graphic design|\\blogo\\b|illustrat|packaging|flyer|t-shirt|video edit|videograph|photograph|retouch|youtube|tiktok|instagram|social media|influencer|\\bugc\\b|public relations|dietitian|nutrition|fitness|coach|tutor|teach|medical|nurse|therap|legal|lawyer|attorney|paralegal|insurance|real estate|interior design|fashion|jewelry|recipe|\\bmenu\\b|\\bchef\\b|music|podcast|travel|logistics|freight|product research|sourcing|procurement|cleaning|construction|plumb|meta ads|google ads|facebook ads|talent book", 'i');

// The word that shows a job is not software work, or null when it may be (or looks like it is)
export function unrelated(title, skills, description) {
  title = title || '';
  const tags = (skills || []).join(' | ');
  if (TECH.test(title) || TECH.test(tags) || CODE.test(title) || CODE.test(description || '')) return null;
  const hit = OTHER.exec(title) || OTHER.exec(tags);
  return hit ? hit[0] : null;
}
