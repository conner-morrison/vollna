#!/usr/bin/env python3
"""Drop jobs that are plainly not software work, before anything is looked up for them.

No AI: two word lists. A job is unrelated only when nothing about it looks technical AND its title
or skill tags name other work (bookkeeping, sales, video editing, …). Anything vague is kept, because
missing a real job costs far more than letting a stray one through.

- TECH is checked on the title and the skill tags. One hit anywhere keeps the job.
- CODE is checked on the title and the description. Only words a non-software post would not use in passing:
  "AI", "app" or "CRM" show up in sales and marketing posts too, so they count in the title and
  skills but not here.
- OTHER is checked on the title and the skill tags, and only when neither of the above found anything.
"""
import re


def words(pattern):
    return re.compile(pattern.replace('\n', ''), re.I)


TECH = words(r'''software|develop|programm|\bcod(e|er|ers|ing)\b|engineer|\bapi\b|\bapis\b|\bapps?\b|application|website|web site|
\bweb\b|landing page|frontend|front-end|backend|back-end|full[- ]?stack|devops|\bcloud\b|\baws\b|azure|\bgcp\b|database|\bsql\b|
mongo|postgres|mysql|firebase|supabase|python|javascript|typescript|\bjava\b|node\.?js|react|\bvue\b|angular|next\.?js|\bphp\b|
laravel|django|flask|ruby|rails|golang|\brust\b|c\+\+|c#|\.net\b|\bswift\b|kotlin|flutter|android|\bios\b|saas|\bcrm\b|\berp\b|
integrat|automat|script|\bbots?\b|chatbot|scrap(e|er|ing)|crawl|n8n|zapier|make\.com|airtable|bubble|webflow|wordpress|shopify|
\bwix\b|squarespace|plugin|extension|\bhtml|\bcss\b|\bui\b|\bux\b|figma|dashboard|machine learning|\bml\b|\bai\b|\bllm|gpt|
openai|claude|gemini|agent dev|algorithm|blockchain|smart contract|solidity|web3|\bgame\b|\bunity\b|unreal|embedded|firmware|
microcontroller|arduino|raspberry|\biot\b|electronic|\bpcb\b|fpga|verilog|vhdl|linux|docker|kubernetes|cyber|security|penetration|
it support|excel|\bvba\b|google sheets|apps script|\bqa\b|hosting|\bdns\b|\bseo\b|twilio|stripe|dialer|voip|\bcad\b|matlab|
\bgis\b|data scien|data analy|data engineer|data architect|computer vision|tech stack|github|deploy''')

CODE = words(r'''\bsoftware (developer|engineer|development)|\bdeveloper\b|\bprogramm(er|ing)\b|source code|codebase|\bapi\b|\bapis\b|
\bsdk\b|github|gitlab|\bpython\b|javascript|typescript|\bjava\b|node\.?js|\breact\b|\bvue\b|angular|next\.?js|\bphp\b|laravel|
django|flask|ruby on rails|golang|\brust\b|c\+\+|c#|\.net\b|\bswift\b|kotlin|flutter|\bsql\b|postgres|mysql|mongodb|firebase|
supabase|\baws\b|docker|kubernetes|\bhtml\b|\bcss\b|wordpress|shopify (app|theme|develop)|webhook|\bjson\b|backend|back-end|
frontend|front-end|full[- ]?stack|firmware|embedded|microcontroller|verilog|n8n|zapier|make\.com|apps script|\bvba\b|
\b(build|create|make|develop|set up)\b[^.|\n]{0,40}?\b(apps?|application|website|tool|platform|dashboard|bot|integration|plugin|
extension|calculator|portal|system|software|script|database|crm)\b|
\b(develop|code|program|script|automate) (a|an|the|our|my)\b''')

OTHER = words(r'''bookkeep|accounting|accountant|\btax\b|payroll|quickbooks|\bxero\b|\baudit\b|\bcpa\b|
copywrit|ghostwrit|proofread|translat|transcri|subtitl|voice[- ]?over|voice act|narrat|
\bsales\b|closer|cold call|telemarket|appointment setting|lead generation|recruit|virtual assistant|executive assistant|
executive support|customer service|customer support|
graphic design|\blogo\b|illustrat|packaging|flyer|t-shirt|
video edit|videograph|photograph|retouch|youtube|tiktok|instagram|social media|influencer|\bugc\b|public relations|
dietitian|nutrition|fitness|coach|tutor|teach|medical|nurse|therap|legal|lawyer|attorney|paralegal|insurance|
real estate|interior design|fashion|jewelry|recipe|\bmenu\b|\bchef\b|music|podcast|travel|logistics|freight|
product research|sourcing|procurement|cleaning|construction|plumb|meta ads|google ads|facebook ads|talent book''')


def unrelated(title, skills=(), description=''):
    """The word that shows a job is not software work, or None when it may be (or looks like it is)."""
    title = title or ''
    tags = ' | '.join(skills or [])
    if TECH.search(title) or TECH.search(tags) or CODE.search(title) or CODE.search(description or ''):
        return None
    hit = OTHER.search(title) or OTHER.search(tags)
    return hit.group(0) if hit else None
