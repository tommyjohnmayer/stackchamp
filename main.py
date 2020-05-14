import os
import urllib
import cgi
import random, decimal
import datetime
import math

from google.appengine.api import users
from google.appengine.ext import ndb

import jinja2
import webapp2

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])

class Player(ndb.Model):
	name = ndb.StringProperty()

class League(ndb.Model):
	name = ndb.StringProperty()

class Season(ndb.Model):
	name = ndb.StringProperty()
	def tournaments(self):
		return Tournament.query(ancestor=self.key).order(Tournament.date)
	def ov_standings(self):
		overall = TPlayer.query(ancestor=self.key).order(TPlayer.player_id)
		tp = ''
		a = []
		tot = 0
		for tplayer in overall:
			if tplayer.player_id != tp:
				if tplayer.knock_order == 0:
					tot = tplayer.key.parent().get().next_points()
				else:
					tot = tplayer.points
			else:
				if tplayer.knock_order == 0:
					tot += tplayer.key.parent().get().next_points()
				else:
					tot += tplayer.points
				a.pop()
			a.append([tplayer.name, tot])
			tp = tplayer.player_id
		a = sorted(a, key=lambda points: points[1], reverse=True)
		return a

class SPlayer(ndb.Model):
	name = ndb.StringProperty()
	player_id = ndb.StringProperty()
	points = ndb.IntegerProperty()
	wins = ndb.IntegerProperty()
	average = ndb.IntegerProperty()

class Payout_Schedule(ndb.Model):
	name = ndb.StringProperty()

class Payout_Detail(ndb.Model):
	payout_schedule = ndb.StructuredProperty(Payout_Schedule)
	num_paid = ndb.IntegerProperty()
	place = ndb.IntegerProperty()
	rate = ndb.FloatProperty()

class Blind_Schedule(ndb.Model):
	name = ndb.StringProperty()

class Blind_Round(ndb.Model):
	blind_schedule = ndb.StructuredProperty(Blind_Schedule)
	round = ndb.IntegerProperty()
	small = ndb.IntegerProperty()
	big = ndb.IntegerProperty()
	ante = ndb.IntegerProperty()

class T_Addon(ndb.Model):
	name = ndb.StringProperty()
	cost = ndb.IntegerProperty()
	count = ndb.IntegerProperty(default = 1)
	checked = ndb.BooleanProperty()

class T_Expense(ndb.Model):
	name = ndb.StringProperty()
	amount = ndb.IntegerProperty()
	cleared = ndb.BooleanProperty(default=False)

class Tournament(ndb.Model):
	name = ndb.StringProperty()
	date = ndb.DateProperty()
	buyin = ndb.IntegerProperty()
	chips = ndb.IntegerProperty()
	round = ndb.IntegerProperty(default=1)
	payout_schedule = ndb.StructuredProperty(Payout_Schedule)
	payout_rate = ndb.FloatProperty(default=0.15)
	blind_schedule = ndb.StructuredProperty(Blind_Schedule)
	t_addons = ndb.StructuredProperty(T_Addon, repeated=True)
	t_expenses = ndb.StructuredProperty(T_Expense, repeated=True)
	status = ndb.StringProperty(default='populating', choices=['populating', 'running','paused','finished'])
	round_length = ndb.IntegerProperty()
	start_time = ndb.DateTimeProperty()
	pause_time = ndb.DateTimeProperty()
	multiplier = ndb.FloatProperty()
	play_count = ndb.IntegerProperty( default=0)
	in_count = ndb.IntegerProperty(default=0)
	last_update = ndb.DateTimeProperty(auto_now=True)
	def buyin_tot(self):
		return self.buyin * self.play_count
	def next_points(self):
		if self.multiplier:
			m = self.multiplier
		else:
			m = 1
		if self.in_count == 0:
			place = 1
		else:
			place = self.in_count
		ft = 0
		tot_players = self.play_count	
		paid = 1
		if tot_players > 5:
			paid = 2
		if tot_players > 9:
			paid = 3
		if tot_players > 18:
			paid = 4
		if tot_players > 27:
			paid = 5
		if tot_players > 36:
			paid = 6
		if tot_players > 45:
			paid = 7
		if tot_players > 54:
			paid = 8
		if place <= paid:
			ITMBonusPool = paid * 200
			PayoutRate = Payout_Detail.query(Payout_Detail.payout_schedule == self.payout_schedule, Payout_Detail.num_paid == paid, Payout_Detail.place == place).fetch()
			a = PayoutRate[0].rate
			itm = float(a) * ITMBonusPool / 100
		else:
			itm = 0
		return int(((tot_players - place) * 25 + ft + itm) * m)

	def addon_tot(self):
		a = 0
		for tplayer in TPlayer.query(ancestor = self.key):
			for addon in tplayer.t_addons:
				a+= addon.cost
		return a
	def expense_tot(self):
		a = 0
		for expense in self.t_expenses:
			a+= expense.amount
		return a
	def payout_basis(self):
		return self.buyin_tot() + self.addon_tot() - self.expense_tot()
	def amount_in(self):
		a = 0
		for tplayer in TPlayer.query(ancestor = self.key):
			a+= tplayer.paid
		return a
	def amount_out(self):
		a = 0
		for expense in self.t_expenses:
			if expense.cleared:
				a+=expense.amount
		return a
	def actual_balance(self):
		return self.amount_in() - self.amount_out()
	def t_addon_count(self, addon_index):
		a = TPlayer.query(TPlayer.t_addons.name == self.t_addons[addon_index].name, ancestor = self.key).count()
		return a
	def t_addon_cost(self, addon_index):
		tourney_addon = self.t_addons[addon_index]
		return tourney_addon.cost * self.t_addon_count(addon_index)
	def rem_time(self):
		if self.status == 'populating':
			a = self.round_length * 60
		elif self.status == 'running':
			a = (self.round_length * 60) - ((self.start_time.now() - self.start_time).seconds)
		elif self.status == 'paused':
			c = self.start_time + (self.pause_time.now() - self.pause_time)
			a = (self.round_length * 60) - ((c.now() - c).seconds)
		elif self.status == 'finished':
			a = 0
		return a
	def check_round(self):
		a = self.rem_time()
		b = self.round
		c = datetime.timedelta(minutes=self.round_length)
		d = self.start_time
		e = self.round_length * 60
		while a <= 0:
			b += 1
			a += e
			d += c
		if b > self.round:
			self.start_time = d
			self.round = b
			self.put()
		return b
	def tables(self):
		t_player_in_count = self.in_count
		tables = 1
		while (tables * 9 < t_player_in_count):
			tables += 1
		return tables

class TPlayer(ndb.Model):
	player_id = ndb.StringProperty()
	name = ndb.StringProperty()
	knock_order = ndb.IntegerProperty( default=0)
	points = ndb.IntegerProperty( default=0)
	knock_player_id = ndb.StringProperty()
	paid = ndb.IntegerProperty()
	t_addons = ndb.StructuredProperty(T_Addon, repeated=True)
	buyin = ndb.IntegerProperty()
	seat = ndb.IntegerProperty(default=1)
	table = ndb.IntegerProperty(default=1)
	place = ndb.IntegerProperty()
	def addons(self):
		a = []
		for addon in self.t_addons:
			a.append( addon.name )
		return a
	def player(self):
		return ndb.Key(urlsafe=self.player_id).get()
	def knock_player(self):
		return ndb.Key(urlsafe=self.knock_player_id).get()
	def addon_tot(self):
		a = 0
		for add in self.t_addons:
			a+= add.cost
		return a
	def due(self):
		return self.buyin + self.addon_tot()
	def balance_calc(self):
		return self.due() - self.paid
	def place_calc(self):
		tournament = self.key.parent()
		tot_players = TPlayer.query(ancestor=tournament).count()
		return tot_players - self.knock_order + 1
	def calc_splayer(self):
		tournament = self.key.parent().get()
		season = tournament.key.parent().get()
		splayer = ndb.Key('SPlayer', self.player_id).get()
		if splayer is None:
			splayer = SPlayer(parent = season.key, id=self.player_id)
			splayer.player_id = self.player_id
			splayer.name = self.name
		tplays = TPlayer.query(TPlayer.player_id == self.player_id, ancestor=season.key).order(-TPlayer.points)
		a = 0
		b = 0
		c = 0
		i = 0
		for tplay in tplays:
			a += tplay.points
			if tplay.place == 1:
				b += 1
			if i <= 3:
				c += tplay.points
				i +=1
		splayer.points = a
		splayer.wins = b
		if i >= 3:
			splayer.average = c / 4
		else:
			splayer.average = 0
		splayer.put()
	def _post_put_hook(self, future):
		tournament = self.key.parent().get()
		tournament.play_count = TPlayer.query(ancestor=tournament.key).count()
		tournament.in_count = TPlayer.query(TPlayer.knock_order == 0, ancestor=tournament.key).count()
		i = 0
		for t_addon in tournament.t_addons:
			t_addon.count = tournament.t_addon_count(i)
			i += 1
		tournament.put()

class Admin(webapp2.RequestHandler):
	def get(self):
		payouts = Payout_Schedule.query()
		blinds = Blind_Schedule.query()
		template_values = {
			'payouts': payouts,
			'blinds': blinds,
		}
		template = JINJA_ENVIRONMENT.get_template('admin.html')
		self.response.write(template.render(template_values))

class MainPage(webapp2.RequestHandler):
    def get(self):
        leagues = League.query()
        template_values = {
			'leagues': leagues,
        }
        template = JINJA_ENVIRONMENT.get_template('index.html')
        self.response.write(template.render(template_values))

class ViewLeague(webapp2.RequestHandler):
	def get(self, league_name):
		league = League.get_by_id(league_name)
		seasons = Season.query(ancestor = league.key).order(-Season.name)
		payouts = Payout_Schedule.query()
		blinds = Blind_Schedule.query()
		template_values = {
			'payouts': payouts,
			'seasons': seasons,
			'blinds': blinds,
			'league': league,
		}
		template = JINJA_ENVIRONMENT.get_template('league.html')
		self.response.write(template.render(template_values))

class ViewTournament(webapp2.RequestHandler):
	def get(self, league_name, season_name, tournament_name):
		tournament = ndb.Key('League', league_name, 'Season', season_name, 'Tournament', tournament_name).get()
		league = ndb.Key('League', league_name)
		tournament.check_round()
		tplayers = TPlayer.query(ancestor = tournament.key).order(-TPlayer.knock_order, TPlayer.table, TPlayer.seat).fetch()
		tplayer_ids = []
		for tplayer in tplayers:
			tplayer_ids.append(tplayer.player_id)
		players = Player.query(ancestor = league).order(Player.name)
		buyin_tot = tournament.play_count * tournament.buyin
		addon_tot = tournament.addon_tot()
		expense_tot = tournament.expense_tot()
		amount_in = tournament.amount_in()
		amount_out = tournament.amount_out()
		payout_basis =  buyin_tot + addon_tot - expense_tot
		tot_players = tournament.play_count
		tot_chips = tot_players * tournament.chips
		paid = 1
		if tot_players > 5:
			paid = 2
		if tot_players > 9:
			paid = 3
		if tot_players > 18:
			paid = 4
		if tot_players > 27:
			paid = 5
		if tot_players > 36:
			paid = 6
		if tot_players > 45:
			paid = 7
		if tot_players > 54:
			paid = 8
		payouts = Payout_Detail.query(Payout_Detail.payout_schedule == tournament.payout_schedule, Payout_Detail.num_paid == paid).order(Payout_Detail.place)
		blinds = Blind_Round.query(Blind_Round.blind_schedule == tournament.blind_schedule, Blind_Round.round >= tournament.round).order(Blind_Round.round).fetch(2)
		if tournament.in_count:
			ave_chips = tot_chips / tournament.in_count
		else:
			ave_chips = 0
		template_values = {
			'payout_basis': payout_basis,
			'tplayer_ids': tplayer_ids,
			'buyin_tot': buyin_tot,
			'addon_tot': addon_tot,
			'amount_in': amount_in,
			'amount_out': amount_out,
			'expense_tot': expense_tot,
			'payouts': payouts,
			'blinds': blinds,
			'tot_chips': tot_chips,
			'ave_chips': ave_chips,
			'tplayers': tplayers,
			'players': players,
			'tournament': tournament,
			'tournament_name': tournament_name,
			'season_name': season_name,
			'league_name': league_name,
		}
		template = JINJA_ENVIRONMENT.get_template('tournament.html')
		self.response.write(template.render(template_values))

class NewTournament(webapp2.RequestHandler):
	def post(self, league_name):
		season = ndb.Key(urlsafe=self.request.get('season')).get()
		tournament = Tournament(parent = season.key, id=self.request.get('name'))
		tournament.name = self.request.get('name')
		tournament.buyin = int(self.request.get('buyin'))
		tournament.chips = int(self.request.get('chips'))
		tournament.date = datetime.datetime.strptime(self.request.get('date'), '%m/%d/%Y')
		tournament.payout_schedule = Payout_Schedule.get_by_id(int(self.request.get('payout_schedule')))
		tournament.blind_schedule = Blind_Schedule.get_by_id(int(self.request.get('blind_schedule')))
		tournament.round_length = int(self.request.get('length'))
		tournament.multiplier = float(self.request.get('multiplier'))
		tournament.put()
		self.redirect('/'+league_name)

class Unknock(webapp2.RequestHandler):
	def post(self, league_id, season_id, tournament_id):
		tplayer = ndb.Key(urlsafe=self.request.get('tplayer')).get()
		tplayer.knock_order = 0
		tplayer.knock_player_id = None
		tplayer.place = None
		tplayer.points = 0
		tplayer.put()
		tplayer.calc_splayer()
		self.redirect('/'+league_id+'/'+season_id+'/'+tournament_id)

class Shuffle(webapp2.RequestHandler):
	def get(self, league_name, season_name, tournament_name):
		tournament = ndb.Key('League', league_name, 'Season', season_name, 'Tournament', tournament_name).get()
		tplayers_in = TPlayer.query(TPlayer.knock_order == 0, ancestor = tournament.key ).fetch()
		t_player_in_count = len(tplayers_in)
		tables = 1
		while (tables * 9 < t_player_in_count):
			tables += 1
		play_per_table = int(math.ceil(float(t_player_in_count) / tables))
		random.shuffle(tplayers_in)
		t = 1
		s = 1
		for tplayer in tplayers_in:
			tplayer.table = t
			tplayer.seat = s
			tplayer.put()
			t += 1
			if t > tables:
				t =1
				s += 1
		self.redirect('/'+league_name+'/'+season_name+'/'+tournament_name)

class Pause(webapp2.RequestHandler):
	def get(self, league_name, season_name, tournament_name):
		tournament = ndb.Key('League', league_name, 'Season', season_name, 'Tournament', tournament_name).get()
		if tournament.start_time:
			s_time = tournament.start_time
		else:
			s_time = datetime.datetime.utcnow()
		if tournament.pause_time:
			p_time = tournament.pause_time
		else:
			p_time = datetime.datetime.utcnow()
		if tournament.status == 'populating':
			tournament.status = 'running'
			tournament.start_time = datetime.datetime.utcnow()
		elif tournament.status == 'running':
			tournament.status = 'paused'
			tournament.pause_time = datetime.datetime.utcnow()
		elif tournament.status == 'paused':
			tournament.status = 'running'
			tournament.start_time = s_time + (datetime.datetime.utcnow() - p_time)
		elif tournament.status == 'finished':
			tournament.status = 'finished'
		tournament.put()
		self.redirect('/'+league_name+'/'+season_name+'/'+tournament_name)

class Knock(webapp2.RequestHandler):
	def post(self, league_id, season_id, tournament_id):
		tplayer = ndb.Key(urlsafe=self.request.get('tplayer')).get()
		tournament = tplayer.key.parent().get()
		tplayer.knock_order = tournament.play_count - tournament.in_count +1
		tplayer.knock_player_id = self.request.get('knock_player')
		if tournament.multiplier:
			m = tournament.multiplier
		else:
			m = 1		
		place = tplayer.place_calc()
		tplayer.place = place
		ft = 0
		tot_players = tournament.play_count
		paid = 1
		if tot_players > 5:
			paid = 2
		if tot_players > 9:
			paid = 3
		if tot_players > 18:
			paid = 4
		if tot_players > 27:
			paid = 5
		if tot_players > 36:
			paid = 6
		if tot_players > 45:
			paid = 7
		if tot_players > 54:
			paid = 8
		if place <= paid:
			ITMBonusPool = paid * 200
			PayoutRate = Payout_Detail.query(Payout_Detail.payout_schedule == tournament.payout_schedule, Payout_Detail.num_paid == paid, Payout_Detail.place == place).fetch()
			a = PayoutRate[0].rate
			itm = float(a) * ITMBonusPool / 100
		else:
			itm = 0
		tplayer.points = int(((tot_players - place) * 25 + ft + itm) * m)
		tplayer.put()
		tplayer.calc_splayer()
		self.redirect('/'+league_id+'/'+season_id+'/'+tournament_id)

class DeleteTplayer(webapp2.RequestHandler):
	def post(self, league_id, season_id, tournament_id):
		tplayer = ndb.Key(urlsafe=self.request.get('tplayer')).get()
		tplayer.key.delete()
		self.redirect('/'+league_id+'/'+season_id+'/'+tournament_id)

class EditTplayer(webapp2.RequestHandler):
	def post(self, league_id, season_id, tournament_id):
		tplayer = ndb.Key(urlsafe=self.request.get('tplayer')).get()
		tournament = tplayer.key.parent().get()
		tplayer.paid = int(self.request.get('paid'))
		tplayer.buyin = tournament.buyin
		tplayer.seat = int(self.request.get('seat'))
		tplayer.table = int(self.request.get('table'))
		addons = self.request.get_all('addon')
		a = []
		for addon in addons:
			i = int(addon)
			a.append( tournament.t_addons[i])
		tplayer.t_addons = a
		tplayer.put()
		self.redirect('/'+league_id+'/'+season_id+'/'+tournament_id)

class AddTplayer(webapp2.RequestHandler):
	def post(self, league_id, season_id, tournament_id):
		tournament = ndb.Key(urlsafe=self.request.get('tournament')).get()
		league = ndb.Key('League', league_id).get()
		tplayer = TPlayer(parent=tournament.key)
		if self.request.get('create') == 'new':
			league = ndb.Key('League', league_id)
			player = Player(parent = league)
			player.name = self.request.get('newplayer')
			player.put()
			tplayer.player_id = player.key.urlsafe()
			tplayer.name = player.name
		else:
			tplayer.player_id = self.request.get('player')
			tplayer.name = ndb.Key(urlsafe=self.request.get('player')).get().name
		tplayer.paid = int(self.request.get('paid'))
		tplayer.due = tournament.buyin
		tplayer.buyin = tournament.buyin
		addons = self.request.get_all('addon')
		a = []
		for addon in addons:
			i = int(addon)
			a.append( tournament.t_addons[i])
		tplayer.t_addons = a
		tplayer.put()
		self.redirect('/'+league_id+'/'+season_id+'/'+tournament_id)

class NewAddon(webapp2.RequestHandler):
	def post(self, league_id, season_id, tournament_id):
		tournament = ndb.Key(urlsafe=self.request.get('tournament')).get()
		addon = T_Addon()
		addon.name = self.request.get('name')
		addon.cost = int(self.request.get('cost'))
		if self.request.get('checked') == 'True':
			addon.checked = True
		else:
			addon.checked = False
		tournament.t_addons.append(addon)
		tournament.put()
		self.redirect('/'+league_id+'/'+season_id+'/'+tournament_id)

class DeleteAddon(webapp2.RequestHandler):
	def post(self, league_id, season_id, tournament_id):
		tournament = ndb.Key(urlsafe=self.request.get('tournament')).get()
		rem_addon = self.request.get('addon')
		i = 0
		for addon in tournament.t_addons:
			if addon.name == rem_addon:
				tournament.t_addons.remove(addon)
		tournament.put()
		self.redirect('/'+league_id+'/'+season_id+'/'+tournament_id)

class NewExpense(webapp2.RequestHandler):
	def post(self, league_id, season_id, tournament_id):
		tournament = ndb.Key(urlsafe=self.request.get('tournament')).get()
		expense = T_Expense()
		expense.name = self.request.get('name')
		expense.amount = int(self.request.get('amount'))
		tournament.t_expenses.append(expense)
		tournament.put()
		self.redirect('/'+league_id+'/'+season_id+'/'+tournament_id)

class CheckUpdate(webapp2.RequestHandler):
	def get(self, league_id, season_id, tournament_id):
		tournament = ndb.Key('League', league_id, 'Season', season_id, 'Tournament', tournament_id).get()
		self.response.write(tournament.last_update)

class DeleteExpense(webapp2.RequestHandler):
	def post(self, league_id, season_id, tournament_id):
		tournament = ndb.Key(urlsafe=self.request.get('tournament')).get()
		rem_expense = self.request.get('expense')
		for expense in tournament.t_expenses:
			if expense.name == rem_expense:
				tournament.t_expenses.remove(expense)
		tournament.put()
		self.redirect('/'+league_id+'/'+season_id+'/'+tournament_id)

class ClearExpense(webapp2.RequestHandler):
	def post(self, league_id, season_id, tournament_id):
		tournament = ndb.Key(urlsafe=self.request.get('tournament')).get()
		clear_expense = self.request.get('expense')
		for expense in tournament.t_expenses:
			if expense.name == clear_expense:
				expense.cleared = True
				tournament.put()
		self.redirect('/'+league_id+'/'+season_id+'/'+tournament_id)

class NewLeague(webapp2.RequestHandler):
	def post(self):
		league = League(id=self.request.get('name'))
		league.name = self.request.get('name')
		league.put()
		self.redirect('/')

class Standings(webapp2.RequestHandler):
	def get(self, league_name, season_name):
		season = ndb.Key('League', league_name, 'Season', season_name).get()
		overall = season.ov_standings()
		winners = SPlayer.query(SPlayer.wins > 0, ancestor=season.key).order(-SPlayer.wins)
		points = SPlayer.query(SPlayer.wins == 0, ancestor=season.key).order(SPlayer.wins, -SPlayer.points).fetch(9)
		a = points[::-1][0].points
		average = SPlayer.query(SPlayer.points < a, SPlayer.wins == 0, ancestor=season.key).order(-SPlayer.points).fetch()
		average = sorted(average, key=lambda splayer: -splayer.average)[:3]
		template_values = {
			'season': season,
			'overall': overall,
			'winners': winners,
			'points': points,
			'average': average,
		}
		template = JINJA_ENVIRONMENT.get_template('standings.html')
		self.response.write(template.render(template_values))

class NewSeason(webapp2.RequestHandler):
	def post(self, league_name):
		league = League.get_by_id(league_name)
		season = Season(parent = league.key, id=self.request.get('name'))
		season.name = self.request.get('name')
		season.put()
		self.redirect('/'+league_name)

class NewPayout(webapp2.RequestHandler):
	def post(self):
		payout = Payout_Schedule()
		payout.name = self.request.get('name')
		payout.put()
		self.redirect('/admin')

class NewBlind(webapp2.RequestHandler):
	def post(self):
		blind = Blind_Schedule()
		blind.name = self.request.get('name')
		blind.put()
		self.redirect('/admin')

class Blind(webapp2.RequestHandler):
	def get(self, blind_id):
		blind = Blind_Schedule.get_by_id(int(blind_id))
		details = Blind_Round.query(Blind_Round.blind_schedule == blind).order(Blind_Round.round)
		template_values = {
			'details': details,
			'blind_id': blind_id,
		}
		template = JINJA_ENVIRONMENT.get_template('blind.html')
		self.response.write(template.render(template_values))

class Payout(webapp2.RequestHandler):
	def get(self, payout_id):
		payout = Payout_Schedule.get_by_id(int(payout_id))
		details = Payout_Detail.query(Payout_Detail.payout_schedule == payout).order(Payout_Detail.num_paid, Payout_Detail.place)
		template_values = {
			'details': details,
			'payout_id': payout_id,
		}
		template = JINJA_ENVIRONMENT.get_template('payout.html')
		self.response.write(template.render(template_values))

class NewPayoutDetail(webapp2.RequestHandler):
	def post(self, payout_id):
		payout = Payout_Schedule.get_by_id(int(payout_id))
		payout_detail = Payout_Detail()
		payout_detail.payout_schedule = payout
		payout_detail.num_paid = int(self.request.get('num_paid'))
		payout_detail.place = int(self.request.get('place'))
		payout_detail.rate = float(self.request.get('rate'))
		payout_detail.put()
		self.redirect('/admin/payout/'+payout_id)

class HelloWorldHandler(webapp2.RequestHandler):
	def get(self):
		# Create the handler's response "Hello World!" in plain text.
		self.response.headers['Content-Type'] = 'text/plain'
		self.response.out.write('Hello World!')

class NewBlindRound(webapp2.RequestHandler):
	def post(self, blind_id):
		blind = Blind_Schedule.get_by_id(int(blind_id))
		blind_round = Blind_Round()
		blind_round.blind_schedule = blind
		blind_round.round = int(self.request.get('round'))
		blind_round.small = int(self.request.get('small'))
		blind_round.big = int(self.request.get('big'))
		blind_round.ante = int(self.request.get('ante'))
		blind_round.put()
		self.redirect('/admin/blind/'+blind_id)

app = webapp2.WSGIApplication([
	('/', MainPage),
	('/NewLeague', NewLeague),
	('/NewPayout', NewPayout),
	('/NewBlind', NewBlind),
	('/admin', Admin),
	('/admin/payout/(\d+)', Payout),
	('/admin/blind/(\d+)', Blind),
	('/admin/payout/(\d+)/NewPayoutDetail', NewPayoutDetail),
	('/admin/blind/(\d+)/NewBlindRound', NewBlindRound),
	('/(\w+)', ViewLeague),
	('/(\w+)/NewTournament', NewTournament),
	('/(\w+)/NewSeason', NewSeason),
	('/(\w+)/(\w+)', Standings),
	('/(\w+)/(\w+)/(\w+)', ViewTournament),
	('/(\w+)/(\w+)/(\w+)/AddTplayer', AddTplayer),
	('/(\w+)/(\w+)/(\w+)/EditTplayer', EditTplayer),
	('/(\w+)/(\w+)/(\w+)/DeleteTplayer', DeleteTplayer),
	('/(\w+)/(\w+)/(\w+)/Knock', Knock),
	('/(\w+)/(\w+)/(\w+)/Unknock', Unknock),
	('/(\w+)/(\w+)/(\w+)/Expense', NewExpense),
	('/(\w+)/(\w+)/(\w+)/DeleteExpense', DeleteExpense),
	('/(\w+)/(\w+)/(\w+)/ClearExpense', ClearExpense),
	('/(\w+)/(\w+)/(\w+)/Addon', NewAddon),
	('/(\w+)/(\w+)/(\w+)/Shuffle', Shuffle),
	('/(\w+)/(\w+)/(\w+)/Pause', Pause),
	('/(\w+)/(\w+)/(\w+)/DeleteAddon', DeleteAddon),
	('/(\w+)/(\w+)/(\w+)/CheckUpdate', CheckUpdate),
], debug=True)
