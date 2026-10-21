import time
import logging
import json
from pathlib import Path
from typing import Optional, Set, Callable, List, Dict, Any
from copy import deepcopy
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By

# Import the graph store (assumes rag_store.py is in the same directory or accessible)
# --- vertiscope: the ONLY edit to this file ------------------------------------
# Copied byte-identical from web_fiber_haptics/backend/dom_deep_serializer.py
# (md5 4d269ea19f9350c6c6c000c620687100) except for these two imports, which
# are guarded so the module loads without the mothership's Kuzu store and 3D
# layout generator. Neither is part of the algorithm under comparison: the
# algorithm is EXTRACT_DOM_JSON_JS + _compute_merkle_hashes + _process_node,
# and those run here exactly as written. The baseline calls *this* code
# rather than a re-implementation of it, because a baseline you paraphrased
# is a baseline you can accidentally flatter.
# The two upstream imports are REMOVED, not guarded:
#
#     from backend.rag_store import FibreGraphStoreV2
#     from backend.ontology.layout_generator import LayoutGenerator
#
# A try/except still names `backend`, and tests/test_architecture.py's
# `test_no_upstream_backend_imports` reads the AST, not the runtime — rightly,
# because an exemption list in an architecture guard is a hole that grows.
# Both names are storage and 3D layout; `__init__` and `scan` are the only
# users and neither is called here. The baseline drives the algorithm
# directly: EXTRACT_DOM_JSON_JS, _compute_merkle_hashes, _process_node.
FibreGraphStoreV2 = None
LayoutGenerator = None
# --- end vertiscope edit -------------------------------------------------------

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# --- JAVASCRIPT: EXTRACT CURRENT DOM STATE AS JSON ---
# This captures the DOM structure, attributes, text, and Shadow Roots.
EXTRACT_DOM_JSON_JS = """
                      function extract(node, depth = 0) {
                          if (!node || depth > 100) return null;
                          
                          let obj = {
                              nodeType: node.nodeType,
                              nodeName: node.nodeName
                          };
                          
                          if (node.nodeType === Node.ELEMENT_NODE) {
                              obj.tagName = node.tagName.toLowerCase();
                              if (node.id) obj.id = node.id;
                              if (node.className && typeof node.className === 'string') obj.className = node.className;
                              
                              // Attributes for identification
                              if (node.attributes.length > 0) {
                                  obj.attributes = {};
                                  for (let attr of node.attributes) {
                                      obj.attributes[attr.name] = attr.value;
                                  }
                              }
                              
                              // Add content hash based on all text inside the node
                              let textContent = node.textContent || '';
                              if (textContent.trim()) {
                                  let hash = 0;
                                  for (let i = 0; i < textContent.length; i++) {
                                      hash = ((hash << 5) - hash) + textContent.charCodeAt(i);
                                      hash |= 0; // Convert to 32bit integer
                                  }
                                  if (!obj.attributes) obj.attributes = {};
                                  obj.attributes['data-content-hash'] = hash.toString(16);
                              }
                              
                              // SHADOW ROOT
                              if (node.shadowRoot) {
                                  obj.shadowRoot = { 
                                      mode: node.shadowRoot.mode, 
                                      children: Array.from(node.shadowRoot.childNodes).map(c => extract(c, depth + 1)).filter(x => x)
                                  };
                              }
                              
                              // CHILDREN
                              obj.children = Array.from(node.childNodes).map(c => extract(c, depth + 1)).filter(x => x);
                          } 
                          else if (node.nodeType === Node.TEXT_NODE) {
                              obj.textContent = node.textContent;
                              if (!obj.textContent.trim()) return null; // Ignore empty whitespace nodes
                          }
                          else if (node.nodeType === Node.COMMENT_NODE) {
                              obj.nodeValue = node.nodeValue;
                          }
                          else if (node.nodeType === Node.DOCUMENT_TYPE_NODE) {
                              obj.name = node.name;
                          }
                          
                          return obj;
                      }
                      return JSON.stringify(extract(document.documentElement));
                      """

class ShadowDOMScanner:
	# Default flipped to False so any caller that forgets to pass a
	# driver still gets a HEADFUL window — the user navigates and
	# triggers snapshots manually, which only works when the browser
	# is visible. Pass ``headless=True`` only for offline tests.
	def __init__(self, headless=False, db_path="fibre_scan.kuzu", driver=None, shared_db=None):
		if driver:
			self.driver = driver
			logger.info("ShadowDOMScanner inherited live active Selenium WebDriver!")
		else:
			profile_path = r"<home>\AppData\Roaming\Mozilla\Firefox\Profiles\iwunpegz.ublock"
			options = Options()
			options.add_argument("-profile")
			options.add_argument(profile_path)
			if headless:
				options.add_argument("--headless")
			self.driver = webdriver.Firefox(options=options)
			self.driver.set_page_load_timeout(60)

		print("[Scanner Debug] >>> Booting FibreGraphStoreV2 Engine...")
		try:
			self.graph_store = FibreGraphStoreV2(db_path=db_path, embed_device="cpu", shared_db=shared_db, disable_embed=True)
			print("[Scanner Debug] >>> Calling graph_store.initialize()...")
			self.graph_store.initialize() # ensures schema exists
			print("[Scanner Debug] >>> Core ontology engine generated seamlessly!")
		except Exception as ge:
			print(f"[Scanner Debug] GRAPH STORE INIT CRITICAL CRASH: {ge}")
			import traceback
			traceback.print_exc()
			raise

		# In-memory set of seen node signatures (for change detection)
		self.seen_signatures = set()

	def _compute_merkle_hashes(self, node: dict) -> str:
		"""Bottom-up traversal to create a strict structural/content hash (Merkle Tree)."""
		if not node: return ""
		
		child_hashes = []
		for child in node.get('children', []):
			child_hashes.append(self._compute_merkle_hashes(child))
			
		shadow = node.get('shadowRoot')
		if shadow:
			for s_child in shadow.get('children', []):
				child_hashes.append(self._compute_merkle_hashes(s_child))
				
		parts = [node.get('tagName', node.get('nodeName', ''))]
		if 'id' in node: parts.append(f"id:{node['id']}")
		if 'className' in node: parts.append(f"class:{node['className']}")
		
		attrs = node.get('attributes', {})
		for key in sorted(attrs.keys()):
			if key.startswith('data-') or key in ['href', 'src', 'aria-label']:
				parts.append(f"{key}:{attrs[key]}")
				
		if node.get('nodeType') == 3: # Text
			text = node.get('textContent', '').strip()
			if text: parts.append(f"txt:{text}")
			
		identity = "|".join(parts) + "||" + "|".join(child_hashes)
		
		import hashlib
		sig = hashlib.sha1(identity.encode('utf-8')).hexdigest()[:16]
		node['_signature'] = sig
		return sig

	def _process_node(self, node: dict, seen_set: Set[str], known_hashes: Set[str] = None) -> Optional[dict]:
		"""Prunes exactly identical subtrees using the Merkle hash."""
		if not node:
			return None

		sig = node.get('_signature')

		# Merkle-based exact subtree pruning
		if sig in seen_set:
			return None
			
		seen_set.add(sig)
		
		new_node = dict(node)
		new_node.pop('children', None)
		new_node.pop('shadowRoot', None)
		
		has_retained_children = False
		
		new_children = []
		for child in node.get('children', []):
			processed = self._process_node(child, seen_set, known_hashes)
			if processed:
				new_children.append(processed)
				has_retained_children = True
		if new_children:
			new_node['children'] = new_children
			
		shadow = node.get('shadowRoot')
		if shadow:
			new_shadow_children = []
			for s_child in shadow.get('children', []):
				processed = self._process_node(s_child, seen_set, known_hashes)
				if processed:
					new_shadow_children.append(processed)
					has_retained_children = True
			if new_shadow_children:
				new_node['shadowRoot'] = {
					'mode': shadow.get('mode'),
					'children': new_shadow_children
				}
				
		# Prune empty wrappers: only keep if it has children OR intrinsic content (DOMAIN_MODEL.md 4.1)
		tag = node.get('tagName', node.get('nodeName', '')).lower()
		is_content_bearing = False
		if node.get('nodeType') == 3:
			if node.get('textContent', '').strip():
				is_content_bearing = True
		else:
			content_tags = {'img', 'video', 'audio', 'picture', 'svg', 'canvas', 'iframe', 'input', 'button', 'select', 'textarea', 'a', 'form'}
			if tag in content_tags:
				is_content_bearing = True
			else:
				attrs = node.get('attributes', {})
				if any(k in attrs for k in ['href', 'src', 'data-src', 'data-href', 'data-url', 'data-link']):
					is_content_bearing = True
					
		if not has_retained_children and not is_content_bearing:
			return None
			
		return new_node

	def _flatten_pruned_tree(self, node: dict, page_url: str, parent_id: str = None) -> tuple:
		"""Walk a pruned tree and produce flat (nodes, links) lists in GUI-ready format.
		Node IDs match what rag_store writes to the database."""
		nodes = []
		links = []
		sig = node.get('_signature', '')
		node_id = f"{page_url}:{sig}"
		tag = node.get('tagName', node.get('tag', node.get('nodeName', '')))

		nodes.append({
			"id": node_id,
			"name": tag,
			"status": "unreviewed",
			"location": tag,
			"url": page_url,
			"tags": [],
			"x": node.get('layout_x', 0.0),
			"y": node.get('layout_y', 0.0),
			"z": node.get('layout_z', 0.0),
		})

		if parent_id:
			links.append({"source": node_id, "target": parent_id, "type": "structure"})

		for child in node.get('children', []):
			cn, cl = self._flatten_pruned_tree(child, page_url, parent_id=node_id)
			nodes.extend(cn)
			links.extend(cl)

		shadow = node.get('shadowRoot')
		if shadow:
			for s_child in shadow.get('children', []):
				cn, cl = self._flatten_pruned_tree(s_child, page_url, parent_id=node_id)
				nodes.extend(cn)
				links.extend(cl)

		return nodes, links

	def scan(self, url, max_duration=60, pause=1.0, offset_x=0.0, on_nodes_flushed: Callable = None):
		"""
		Performs adaptive incremental scanning, storing DOM in Kuzu.

		Args:
		    url (str): The target URL.
		    max_duration (int): Maximum time in seconds to run the scan loop.
		    pause (float): Latency/pause time in seconds between scrolls.
		    offset_x (float): Sequential timeline baseline coordinate block.
		    on_nodes_flushed (callable): Optional callback invoked with
		        {"type": "nodes", "nodes": [...], "links": [...]} after each
		        dedup pass, and {"type": "done"} when the scan finishes.
		"""
		# Only navigate if we aren't identically already there!
		current_url = self.driver.current_url
		if current_url != url and current_url != url + "/":
			logger.info(f"Navigating to {url}...")
			self.driver.get(url)
		else:
			logger.info(f"Browser intrinsically locked cleanly already on {url}...")

		# Wait for initial page load
		try:
			WebDriverWait(self.driver, 20).until(lambda d: d.execute_script('return document.readyState') == 'complete')
		except:
			logger.warning("Page load timeout or readyState not complete, proceeding anyway.")

		time.sleep(pause)

		print(f"\n[Scanner Debug] >>> Loaded {len(self.seen_signatures)} existing signatures from DB.")
		
		# Load existing hashes to prune identically matching subtree strings natively
		known_hashes = self.graph_store.get_content_hashes_for_url(url)
		print(f"[Scanner Debug] >>> Loaded {len(known_hashes)} content hashes from DB for {url}.")

		start_time = time.time()
		iteration = 0

		print("\n[Scanner Debug] >>> Executing JS extraction logic natively...")
		raw_json = self.driver.execute_script(EXTRACT_DOM_JSON_JS)
		print(f"[Scanner Debug] >>> JS executed natively. Extracted {len(raw_json)} bytes.")
		snapshot = json.loads(raw_json)
		print("[Scanner Debug] >>> JSON loaded properly.")

		# Helper to count total nodes in snapshot
		def count_nodes(node):
			total = 1
			for child in node.get('children', []):
				total += count_nodes(child)
			shadow = node.get('shadowRoot')
			if shadow:
				for s_child in shadow.get('children', []):
					total += count_nodes(s_child)
			return total

		logger.info(f"Total nodes in snapshot: {count_nodes(snapshot)}")

		# Structurally apply the 3D Layout Graph coordinates mapping across the ENTIRE topology before we deduplicate logic
		logger.info(f"Applying Radial Tree geometry structures across sequential offset X={offset_x}...")
		LayoutGenerator.apply_radial_tree_layout(snapshot)

		# Compute bounding radius BEFORE shifting so it reflects the natural graph extent
		bounding_radius = LayoutGenerator.compute_bounding_radius(snapshot)
		print(f"[Scanner Debug] >>> Bounding radius for snapshot: {bounding_radius:.1f}")

		# Offset X mapping!
		def shift_tree(node, dx):
			node['layout_x'] = node.get('layout_x', 0.0) + dx
			for c in node.get('children', []): shift_tree(c, dx)
			if 'shadowRoot' in node:
				for sc in node['shadowRoot'].get('children', []): shift_tree(sc, dx)
		shift_tree(snapshot, offset_x)

		# Process in one pass: get pruned snapshot and update sets
		print("\n[Scanner Debug] >>> Executing 1-Pass deduplication pruning...")
		self._compute_merkle_hashes(snapshot)
		pruned = self._process_node(snapshot, self.seen_signatures, known_hashes)
		print(f"[Scanner Debug] >>> Deduplication pass returned: {'VALID' if pruned else 'NULL (Fully Pruned)'}")
		if pruned:
			try:
				print("[Scanner Debug] >>> Dumping into Kuzu index...")
				self.graph_store.index_dom_snapshot(pruned, url)
				print("[Scanner Debug] >>> Initial snapshot mapped correctly into graph_store!")
				if on_nodes_flushed:
					flat_nodes, flat_links = self._flatten_pruned_tree(pruned, url)
					on_nodes_flushed({"type": "nodes", "nodes": flat_nodes, "links": flat_links, "boundingRadius": bounding_radius, "offsetX": offset_x})
			except Exception as e:
				print(f"[Scanner Debug] FATAL ERROR IN GRAPH STORE: {e}")
				raise
		else:
			print("[Scanner Debug] >>> Initial snapshot fully pruned (no new content).")

		consecutive_no_changes = 0

		while True:
			elapsed = time.time() - start_time
			if elapsed > max_duration:
				logger.info(f"Time limit reached ({max_duration}s). Stopping scan.")
				break

			iteration += 1
			logger.info(f"Iteration {iteration} - Scrolling and scanning...")

			# Try scrolling the main feed container with fallback to standard scroll
			self.driver.execute_script("""
				let container = document.querySelector('[data-testid="feedScrollView"]');
				if (container) {
					container.scrollBy(0, container.clientHeight);
				} else {
					window.scrollBy(0, window.innerHeight);
				}
			""")
			
			# Wait for network idle
			try:
				WebDriverWait(self.driver, 10).until(
					lambda d: d.execute_script("return window.performance.getEntries().length > 0")
				)
			except:
				pass

			time.sleep(pause)
			time.sleep(1) # additional render time
			
			# Force a "Load More" trigger by simulating a scroll to the bottom
			self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
			time.sleep(1)

			# Fallback: Look for "Load more" / "Show more" buttons aggressively
			try:
				load_more = self.driver.find_element(By.XPATH, "//*[contains(text(),'Load more') or contains(text(),'Show more') or contains(text(),'See more')]")
				load_more.click()
				logger.info("Clicked 'Load more' button.")
				time.sleep(2)
			except:
				pass

			# Capture JSON state
			raw_json = self.driver.execute_script(EXTRACT_DOM_JSON_JS)
			snapshot = json.loads(raw_json)

			# Diagnostic readouts
			logger.info(f"Snapshot has {len(raw_json)} bytes")
			logger.info(f"Total nodes in snapshot: {count_nodes(snapshot)}")
			
			print(f"[Scanner Debug] >>> Applying topology math offsets (X={offset_x}) for iter {iteration}...")
			LayoutGenerator.apply_radial_tree_layout(snapshot)
			bounding_radius = max(bounding_radius, LayoutGenerator.compute_bounding_radius(snapshot))
			shift_tree(snapshot, offset_x)

			# Single pass: detect changes and build pruned snapshot
			print(f"[Scanner Debug] >>> Stripping iteration {iteration}...")
			self._compute_merkle_hashes(snapshot)
			pruned = self._process_node(snapshot, self.seen_signatures, known_hashes)
			print(f"[Scanner Debug] >>> Pruned tree available: {'YES' if pruned else 'NO'}")

			if pruned:
				consecutive_no_changes = 0
				self.graph_store.index_dom_snapshot(pruned, url)
				logger.info("New content stored.")
				if on_nodes_flushed:
					flat_nodes, flat_links = self._flatten_pruned_tree(pruned, url)
					on_nodes_flushed({"type": "nodes", "nodes": flat_nodes, "links": flat_links, "boundingRadius": bounding_radius, "offsetX": offset_x})
			else:
				consecutive_no_changes += 1
				logger.info(f"No new content ({consecutive_no_changes}/3).")
				if consecutive_no_changes >= 3:
					logger.info("Stopping scan (no changes).")
					break

		if on_nodes_flushed:
			on_nodes_flushed({"type": "done"})

		logger.info("Deduplication complete. Serializing to HTML from graph...")
		final_html = self.graph_store.serialize_dom_to_html(url)
		return final_html

	def close(self):
		self.driver.quit()
		# Graph store persists; we don't close it explicitly


def scan(target="https://www.tarot.com/", max_duration=60, pause=1.0, scanner=None, output_folder="./sources"):
	if scanner is None:
		scanner = ShadowDOMScanner(headless=False) # headless=False as per original

	name = target.replace("https://", "").replace("www.", "").replace("/", "").replace(".", "_").replace("?", "").replace("=", "").replace("-", "")

	final_html = scanner.scan(target, max_duration=max_duration, pause=pause, offset_x=0.0)

	Path(output_folder).mkdir(exist_ok=True)
	out_path = f"{output_folder}/{name}.html"
	with open(out_path, "w", encoding="utf-8") as f:
		f.write(final_html)

	print("=" * 60)
	print("ADAPTIVE SCAN COMPLETE")
	print("=" * 60)
	print(f"Saved to: {out_path}")
	print(f"File Size: {len(final_html) / 1024 / 1024:.2f} MB")
	print("The file contains the cumulative state of all scrolled content.")
	scanner.close()
	return out_path


if __name__ == "__main__":

	urls = [
		"https://bsky.app/profile/preyervallis.bsky.social"
		#"https://bsky.app/"
		#"https://www.archive.org/",
		#"https://www.tarot.com/search?q=love&size=n_20_n", 
		#"https://copykat.com/?s=love",
		#"https://www.adafruit.com/search?q=touchscreen", 
		#"https://www.wiki.gg/wikis", 
		#"https://www.criterion.com/search?q=zizek", 
		#"https://duckduckgo.com/?q=love&atb=v473-1&ia=web", 
		#"https://www.youtube.com/watch?v=uIHf-JSPFec",
		#"https://ddosecrets.org/all_articles/recent", 
		#"https://www.rom.on.ca/", 
		#"https://www.crystalvaults.com/crystal-guide/", 
		#"https://www.rollingstone.com/", 
		#"https://neocities.org/browse", 
		#"https://unicornriot.ninja/", 
		#"https://www.democracynow.org/", 
		#"https://www.cbc.ca/news", 
		#"https://thecanadianencyclopedia.ca/en", 
		#"https://asc-cybernetics.org/definitions/", 
		#"https://www.foreignobjekt.com/artists", 
		#"https://www.posthumanschool.com/", 
		#"https://www.deepobjekt.com/", 
		#"https://plato.stanford.edu/entries/peirce-semiotics/", 
		#"https://copykat.com/", 
		#"https://ioccult.com/occult-tradition/hermeticism-explained/", 
		#"https://www.ctvnews.ca/", 
		#"https://letitroll.eu/", 
		#"https://neuroheadz.com/pages/events",
		#"https://neurofunkradio.com/how-neurofunk-is-taking-over-drum-and-bass-festivals-worldwide/"
		#"https://www.allrecipes.com/must-have-cookie-recipes-11807527", 
		#"https://substack.com/explore",
		#"https://www.foodnetwork.com/recipes", 
		#"https://www.similarsites.com/", 
		#"http://www.opeth.com/", 
		#"https://massacremerch.com/collections/mire-lore", 
		#"https://www.spirit-of-metal.com/en/band/Mire_Lore", 
		#"https://frankriggio.com/", 
		#"https://emastered.com/blog/what-is-neurofunk"
		#"https://www.posthumanart.com/", 
		#"https://www.olympics.com/en/milano-cortina-2026"
		#"https://www.crystalvaults.com/crystal-encyclopedia/aegirine"
		#"https://tastedive.com/movies", 
		#"https://tastedive.com/movies/like/Bringing-Out-The-Dead-Movie", 
		#"https://ww8.123moviesfree.net/", 
		#"https://ww8.123moviesfree.net/movie/shackleton-the-greatest-story-of-survival-1630857335/", 
		#"https://ww8.123moviesfree.net/movie/the-settlers-1630856832/", 
		#"https://tastedive.com/movies/like/sabor-tropical", 
		#"https://tastedive.com/movies/like/Mad-World-2018", 
		#"https://tastedive.com/movies/like/Barbarian-Queen-II-The-Empress-Strikes-Back", 
		#"https://tastedive.com/movies/like/Bat-21", 
		#"https://tastedive.com/movies/like/The-Imaginarium-Of-Doctor-Parnassus", 
		#"https://tastedive.com/movies/like/The-Exigency", 
		#"https://tastedive.com/movies/like/Heart-String-Marionette-2012", 
		#"https://tastedive.com/movies/like/The-Cockpit", 
		#"https://tastedive.com/movies/like/Renaissance-Man-Movie", 
		#"https://tastedive.com/movies/like/Amici-Miei-Atto-Iiideg", 
		#"https://tastedive.com/movies/like/Earth-1996", 
		#"https://tastedive.com/movies/like/bela-kiss-prologue", 
		#"https://tastedive.com/movies/like/Ghost-Ship-1952", 
		#"https://tastedive.com/movies/like/Tonari-No-Yae-Chan", 
	]
	for url in urls:
		scan(target=url, max_duration=20000, pause=0.1)