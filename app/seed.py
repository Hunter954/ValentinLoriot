from . import db
from .models import Client, Project

def seed_demo():
    if Project.query.first():
        return
    names = ["South Park", "Varsity Rugby", "American Vintage", "Borocato", "Castilho", "Caribbean Sea", "American Vintage Sports Club", "Bo'jardin"]
    clients=[]
    for i,n in enumerate(names):
        c=Client(name=n, sort_order=i, is_featured=True)
        db.session.add(c); clients.append(c)
    db.session.flush()
    desc = "Film de présentation du domaine viticole — tournage sur 2 jours, du lever de soleil sur les vignes jusqu'à la dégustation en cave. Vidéo + reportage photographique complet."
    p=Project(title="Château Gasqui", slug="chateau-gasqui", category="Vigne & hôtellerie", location="Var, France", year="2024", type_label="Film", duration="3 min 42 s", description=desc, is_featured=True, is_reel=True, sort_order=1, client_id=clients[0].id)
    db.session.add(p); db.session.commit()
