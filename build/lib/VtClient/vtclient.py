import requests
import asyncio
import concurrent.futures
import json
import functools
import os
import hashlib

class VtClient:
    def __init__(self, vtkey, workers=16, download_directory="downloads"):
        self.WORKERS = workers
        self.session = requests.Session()
        rqAdapters = requests.adapters.HTTPAdapter(
            pool_connections=self.WORKERS, 
            pool_maxsize=self.WORKERS + 4, 
            max_retries=2
        )
        self.session.mount("https://", rqAdapters)
        self.session.mount('http://', rqAdapters)
        self.session.headers.update({
                "Accept-Encoding": "gzip, deflate",
                "User-Agent" : "gzip,  Python Async VirusTotal Client"
        })
        self.vtkey = vtkey
        self.dlDir = download_directory
    

    def report(self, hashval, allinfo = 1):
        url = 'https://www.virustotal.com/vtapi/v2/file/report'
        params = {"apikey": self.vtkey, "resource": hashval, "allinfo":allinfo}
        return self.session.get(url, params=params)
    
    async def _yield_reports(self, hashlist, allinfo=1):
        responses = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.WORKERS) as executor:
            futures = [
                self.loop.run_in_executor(
                    executor,
                    functools.partial(self.report, hashlist[ind], allinfo)
                )
            for ind in range(0, len(hashlist)) if hashlist[ind]]
        
        await asyncio.gather(*futures)

        for ind in range(0, len(futures)):
            resp = futures[ind].result()
            if resp.status_code == 200:
                responses.update({hashlist[ind]: resp.json()})
            else:
                responses.update({hashlist[ind]: "ERROR"})
        
        return responses
    
    def reports(self, hashlist, allinfo=1):
        RESOURCE_CHUNK = 24
        self.loop = asyncio.new_event_loop()
        resource_groups = [",".join(hashlist[ind:ind+RESOURCE_CHUNK]) for ind in range(0, len(hashlist), RESOURCE_CHUNK)]
        for ind in range(0, len(resource_groups), self.WORKERS):
            group = resource_groups[ind:ind+self.WORKERS]
            resp = {}
            for k,v in self.loop.run_until_complete(self._yield_reports(group, allinfo)).items():
                if len(k.split(",")) > 1:
                    for r in v:
                        resp.update({r.get("sha256"):r})
                else:
                    resp.update({k:v})
            yield resp

    
    def search(self, query, maxresults=None):
        hashes = []

        url = "https://www.virustotal.com/vtapi/v2/file/search"
        params = {"apikey": self.vtkey, "query": query}
        while True:
            resp = self.session.post(url, data=params)
            if resp.status_code == 200:
                res = resp.json()
                hashes.extend(res.get("hashes", []))
                if not res.get("offset"):
                    break
                if maxresults:
                    if len(hashes) >= maxresults:
                        break
                params.update({"offset": res.get("offset")})
        
        if maxresults:
            return hashes[:maxresults]
        else:
            return hashes
    
    def search2(self, query, maxresults=None):
        hashes = []

        url = "https://www.virustotal.com/intelligence/search/programmatic/"
        params = {"apikey": self.vtkey, "query": query}
        while True:
            resp = self.session.get(url, params=params)
            if resp.status_code == 200:
                res = resp.json()
                hashes.extend(res.get("hashes", []))
                if not res.get("next_page"):
                    break
                if maxresults:
                    if len(hashes) >= maxresults:
                        break
                params.update({"page": res.get("next_page")})
        
        if maxresults:
            return hashes[:maxresults]
        else:
            return hashes
    
    def integrity(self, content):
        hasher = hashlib.sha256(content)
        return hasher.hexdigest()

    def dl(self, hashval):
        url = "https://www.virustotal.com/intelligence/download/"
        params = {"apikey":self.vtkey, "hash": hashval}
        resp = self.session.get(url, params=params)
        if resp.status_code == 200:
            check = self.integrity(resp.content)
            if check.upper() == hashval.upper():
                with open("{0}/{1}".format(self.dlDir, hashval), "wb") as fout:
                    fout.write(resp.content)
                return {hashval: 'SUCCESS'}
            else:
                return {hashval: 'ERROR - integrity check'}
        else:
            return {hashval: f'ERROR - status code {resp.status_code}'}
    
    async def _yield_downloads(self, hashlist):
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.WORKERS) as executor:
            futures = [
                self.loop.run_in_executor(
                    executor,
                    functools.partial(self.dl, hashlist[ind])
                )
            for ind in range(0, len(hashlist)) if hashlist[ind]]
        await asyncio.gather(*futures)
        return [f.result() for f in futures]

    def download(self, hashlist):
        self.loop = asyncio.new_event_loop()
        if not os.path.exists(self.dlDir):
            os.makedirs(self.dlDir)
        for ind in range(0, len(hashlist), self.WORKERS):
            yield self.loop.run_until_complete(self._yield_downloads(hashlist[ind:ind+self.WORKERS]))
